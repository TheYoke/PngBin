from pngbin import ChainReader

from fuse import Fuse
import fuse
import requests

from errno import EACCES, ENOENT
import sqlite3
import stat
import os


fuse.fuse_python_api = (0, 2)
fuse.feature_assert('stateful_files', 'has_init')

DEFAULT_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0'


class PBFuse(Fuse):
    def __init__(self, *args, **kwargs):
        Fuse.__init__(self, *args, **kwargs)
        self.session = requests.Session()

        # options from `-o` and their default values
        self.meta_db = 'meta.db'
        self.header_file = None

        # these will be initialized in fsinit()
        self.conn = None  # the connection for database file
        self.defstat = {}  # default (directory) stat
        self.statfs_ = fuse.StatVfs()  # returned object for statfs()

    @staticmethod
    def _sqlite_path_func(t, u):
        t = t[u:]
        i = t.find('/') + 1
        return t[:i] if i else t

    def fsinit(self):
        self.conn = sqlite3.connect(f'file:{self.meta_db}?mode=ro', check_same_thread=False, uri=True)
        self.conn.create_function("_PATH", 2, self._sqlite_path_func)
        self.file_class.conn = self.conn
        self.file_class.session = self.session
        
        m = os.stat(self.meta_db)
        self.defstat = {
            'st_mode': stat.S_IFDIR | 0o755, 'st_nlink': 2, 'st_size': 64,
            'st_uid': os.getuid(), 'st_gid': os.getgid(),
            'st_atime': m.st_atime, 'st_mtime': m.st_mtime, 'st_ctime': m.st_ctime}
        
        cur = self.conn.cursor()
        sum_length = cur.execute('SELECT SUM(length) FROM files;').fetchone()[0]
        count_length = cur.execute('SELECT COUNT(length) FROM files;').fetchone()[0]

        self.statfs_.f_bsize = 1048576
        self.statfs_.f_frsize = 4096
        self.statfs_.f_blocks = sum_length // 4096 + bool(sum_length % 4096)
        self.statfs_.f_files = count_length
        self.statfs_.f_flag = os.ST_RDONLY

    def getattr(self, path):
        st = fuse.Stat(**self.defstat)
        if path == '/':
            return st  # if root, just return default stat
        path = path.removeprefix('/') # discard the leading slash, if any
            
        cur = self.conn.cursor()
        cur.execute('SELECT path, length FROM files WHERE path LIKE ?;', (path + '%',))
        for full_path, length in cur:
            if path == full_path:
                st.st_mode = stat.S_IFREG | 0o555
                st.st_nlink = 1
                st.st_size = length
            elif full_path[len(path)] != '/':
                continue
            # else: path is pointed to a directory
    
            return st
        return -ENOENT
    
    def readdir(self, path, _):
        if not path.endswith('/'):
            path += '/'
        path = path.removeprefix('/')  # discard the leading slash, if any
        
        cur = self.conn.cursor()
        cur.execute('SELECT _PATH(path, :u) '
                    'FROM files '
                    'WHERE path LIKE :v '
                    'GROUP BY _PATH(path, :u)',
                    {'u': len(path), 'v': path + '%'})
        name = None
        for (name,) in cur:
            if name.endswith('/'):
                yield fuse.Direntry(name[:-1], type=stat.S_IFDIR)
            else:
                yield fuse.Direntry(name, type=stat.S_IFREG)

        if name is None:
            return -ENOENT

    def access(self, path, mode):
        st = self.getattr(path)
        if st == -ENOENT:
            return -ENOENT
        for flag in [os.R_OK, os.W_OK, os.X_OK]:
            if mode & flag and not st.st_mode & flag:
                return -EACCES

    def statfs(self):
        return self.statfs_

    class PBFuseFile:
        conn = None
        session = None
        
        def __init__(self, path, flags, *_):
            self._path = path
            print('open:', self._path, flags)
            
            # https://github.com/mafintosh/fuse-bindings/issues/25
            # assert flags == os.O_RDONLY or flags == 32768, flags
            
            self.readers = {}
            path = path.removeprefix('/')  # discard the leading slash, if any
            cur = self.conn.cursor()
            cur.execute('SELECT offset, length, images_id FROM files WHERE path=?;', (path,))
            row = cur.fetchone()
            if row is None:
                raise FileNotFoundError(path)
            self.offset, self.length, self.images_id = row

        def read(self, length, offset):
            reader = self.readers.get(offset, None)
            if reader is None:
                print('read:', self._path, (length, offset))

                reader = ChainReader(
                    self._get_info(self.images_id),
                    self.offset + offset, self.length - offset, decrypt=True, auto_close=True)
                self.readers[offset] = reader

            data = reader.read(length)

            next_offset = offset + len(data)
            if next_offset in self.readers:
                self.readers[next_offset].close()

            self.readers[next_offset] = reader
            del self.readers[offset]
            
            return data

        def release(self, flags):
            print('rlse:', self._path, (flags, len(self.readers)))
            
            for reader in self.readers.values():
                reader.close()

        def _get_stream(self, url):
            def _fobj(first, last):
                headers = {'Range': f'bytes={first}-{last}'}
                err = None
                for _ in range(3):  # if failed, retries two more tries.
                    try:
                        response = self.session.get(url, headers=headers, stream=True, timeout=30.0)
                        if response.status_code != 206:
                            raise NetReaderError('Invalid Status Code (Expect 206): ' + str(response.status_code))
                        ct = response.headers.get('Content-Type', '')
                        if ct != 'image/png':
                            raise NetReaderError('Invalid Content-Type Header: ' + ct)
                        cl = response.headers.get('Content-Length', '')
                        if cl != str((last - first) + 1):
                            raise NetReaderError('Invalid Content-Length Header: ' + cl)
                        return response.raw
                    except requests.RequestException as e:
                        err = e
                else:
                    raise err

            return _fobj

        def _get_info(self, images_id):
            cur = self.conn.cursor()
            while True:
                cur.execute("SELECT key, iv, width, height FROM images WHERE id=?", (images_id,))
                key, iv, width, height = cur.fetchone()

                cur.execute("SELECT url FROM urls WHERE images_id=?", (images_id,))
                url = cur.fetchone()[0]

                yield {
                    'width': width,
                    'height': height,
                    'key': key,
                    'iv': iv,
                    'fobj': self._get_stream(url)
                }
                images_id += 1


    def main(self, *args, **kwargs):
        self.file_class = self.PBFuseFile
        return Fuse.main(self, *args, **kwargs)


class NetReaderError(Exception):
    """ raises when error occurs during _get_stream(). """
    pass


def main():
    pbf = PBFuse(
        usage='Mount Filesystem in Usersapce (FUSE) for PngBin.\n' + Fuse.fusage,
        dash_s_do='setsingle')
    pbf.parser.add_option(
        mountopt="meta_db", metavar="PATH", default='meta.db',
        help='Path to sqlite database file contains the metadata of PngBin images. (default: "%default")')
    pbf.parser.add_option(
        mountopt="header_file", metavar="PATH", default=None,
        help='Path to line-separated "key: value" text file for request headers.')
    pbf.parse(values=pbf, errex=1)

    if pbf.fuse_args.mount_expected():
        if not os.path.isfile(pbf.meta_db):
            exit(f'Database file "{pbf.meta_db}" does not exist or is not a file.')
        if pbf.header_file is not None and not os.path.isfile(pbf.header_file):
            exit(f'Header file "{pbf.header_file}" does not exist or is not a file.')
        
        if pbf.header_file:
            with open(pbf.header_file, 'r') as fobj:
                for line in fobj:
                    key, value = line.strip().split(':', 1)
                    pbf.session.headers[key.strip()] = value.strip()
        if 'User-Agent' not in pbf.session.headers:
            pbf.session.headers['User-Agent'] = DEFAULT_USER_AGENT

    pbf.main()


if __name__ == '__main__':
    main()
