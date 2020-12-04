from pngbin import ChainReader

import flask
import requests

from urllib.parse import quote
import sqlite3
import argparse
import sys
import os


SERVER_DEBUG = False  # if True, run server in debug mode.
DARK_MODE = True  # if True, use dark theme in explorer webui.

APP = flask.Flask(__name__, static_url_path='/__static__')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0'
EXT_TYPES = {  # Type: ['archive', 'audio', 'image', 'pdf', 'text', 'video']
    '.m4a': 'audio', '.mp3': 'audio', '.oga': 'audio', '.ogg': 'audio', '.webma': 'audio', '.wav': 'audio',
    '.7z': 'archive', '.zip': 'archive', '.rar': 'archive', '.gz': 'archive', '.tar': 'archive', '.gif': 'image',
    '.ico': 'image', '.jpe': 'image', '.jpeg': 'image', '.jpg': 'image', '.png': 'image', '.svg': 'image',
    '.webp': 'image', '.pdf': 'pdf', '.txt': 'text', '.atom': 'text', '.bat': 'text', '.bash': 'text', '.c': 'text',
    '.cmd': 'text', '.coffee': 'text', '.css': 'text', '.hml': 'text', '.js': 'text', '.json': 'text', '.java': 'text',
    '.less': 'text', '.markdown': 'text', '.md': 'text', '.php': 'text', '.pl': 'text', '.py': 'text', '.rb': 'text',
    '.rss': 'text', '.sass': 'text', '.scpt': 'text', '.swift': 'text', '.scss': 'text', '.sh': 'text', '.xml': 'text',
    '.yml': 'text', '.plist': 'text', '.htm': 'text', '.html': 'text', '.mhtm': 'text', '.mhtml': 'text',
    '.xhtm': 'text', '.xhtml': 'text', '.mp4': 'video', '.m4v': 'video', '.ogv': 'video', '.webm': 'video',
    '.3g2': 'video', '.3gp': 'video', '.3gp2': 'video', '.3gpp': 'video', '.mov': 'video', '.qt': 'video'
}


def _get_args(argv):
    args = (
        {
            'description': 'Startup a local server for Explorer WebUI.'
        },
        [
            (
                ['--meta_db', '-m'],
                {
                    'default': 'meta.db',
                    'help': 'An sqlite database file contains the metadata of PngBin images. (default: "meta.db")'
                }
            ),
            (
                ['--ip', '-i'],
                {
                    'default': '127.0.0.1',
                    'help': 'IP address for the local server. (default: 127.0.0.1)'
                }
            ),
            (
                ['--port', '-p'],
                {
                    'default': '8080',
                    'help': 'Port number for the local server. (default: 8080)'
                }
            )
        ]
    )

    parser = argparse.ArgumentParser(**args[0])
    for arg in args[1]:
        parser.add_argument(*arg[0], **arg[1])
    return parser.parse_args(argv)


CFG = _get_args(sys.argv[1:])
assert os.path.isfile(CFG.meta_db), f'Database file "{CFG.meta_db}" does not exist.'


class NetReaderError(Exception):
    """ raises when error occurs during _get_stream(). """
    pass


def _get_stream(url):
    def _fobj(first, last):
        headers = {
            'Range': f'bytes={first}-{last}',
            'User-Agent': USER_AGENT}
        err = None
        for _ in range(3):  # if failed, retries two more tries.
            try:
                response = requests.get(url, headers=headers, stream=True, timeout=30.0)
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


def _get_info(cur, images_id):
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
            'fobj': _get_stream(url)
        }
        images_id += 1


def _get_conn(db_path, g=True):
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    if g:
        flask.g.conn = conn
    return conn


@APP.teardown_appcontext
def _close_conn(_=None):
    conn = flask.g.pop('conn', None)
    if conn is not None:
        conn.close()


def _human_bytes(n):
    for k, u in enumerate(['KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB']):
        if n < 1024 ** (k + 2):
            return '{:.2f} {}'.format(n / 1024 ** (k + 1), u)
    else:
        return '{:.2f} YB'.format(n / 1024 ** 8)


def _sqlite_path_func(t, u):
    t = t[u:]
    i = t.find('/') + 1
    return t[:i] if i else t


def page_explorer(path):
    conn = _get_conn(CFG.meta_db)
    conn.create_function("_PATH", 2, _sqlite_path_func)
    cur = conn.cursor()
    cur.execute('SELECT length, _PATH(path, :u) '
                'FROM files '
                'WHERE path LIKE :v '
                'GROUP BY _PATH(path, :u)',
                {'u': len(path), 'v': path + '%'})

    files, dirs = [], []
    for length, name in cur:
        data = {
            'url': '/' + quote(path + name),
            'name': name
        }

        if name.endswith('/'):
            data['name'] = data['name'][:-1]
            dirs.append(data)
        else:
            ext = os.path.splitext(name)[1]
            data['size'] = _human_bytes(length)
            data['type'] = EXT_TYPES.get(ext, 'unknown')
            files.append(data)

    if not (files or dirs):
        flask.abort(404)

    parents, url = [], '/'
    for name in (x for x in path.split('/') if x):
        url += name + '/'
        parents.append({
            'url': quote(url),
            'name': name
        })

    if 'ls' in flask.request.args:
        host_url = flask.request.host_url[:-1]
        return flask.Response(
            '\n'.join(host_url + x['url'] for x in files),
            headers={
                'Content-Type': 'text/plain',
                'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=-1'
            }
        )

    return flask.render_template('explorer.html', **{
        'dirs': dirs,
        'files': files,
        'parents': parents,
        'title': parents[-1]['name'] if parents else '/',
        'theme': 'dark' if DARK_MODE else 'light'
    })


def send_file(path):
    conn = _get_conn(CFG.meta_db, g=False)
    try:
        cur = conn.cursor()
        cur.execute('SELECT offset, length, images_id FROM files WHERE path=?;', (path,))
        row = cur.fetchone()
        if row is None:
            flask.abort(404)

        offset, total_length, images_id = row
        headers = {'Accept-Ranges': 'bytes'}

        if flask.request.range:
            x = flask.request.range.range_for_length(total_length)
            if x is None:
                flask.abort(416)
            first, last = x
            status = 206
            headers['Content-Range'] = flask.request.range.to_content_range_header(total_length)
            length = last - first
        else:
            status = 200
            first = 0
            length = total_length

        first += offset
        headers['Content-Length'] = str(length)
        reader = ChainReader(_get_info(cur, images_id), first, length, decrypt=True, auto_close=True)

        reader_close = reader.close
        reader.close = lambda: reader_close() or conn.close()

        return flask.send_file(
            reader,
            as_attachment='dl' in flask.request.args,
            attachment_filename=os.path.split(path)[1]
        ), status, headers
    except:
        # Developer note:
        #   I use "except" clause instead of "finally" clause because I want to close the connection
        #   if error occurs before this function returns (with "return" clause). But if there is no error,
        #   flask will call close on "reader" automatically when it's done and therefore closing the sqlite connection.
        conn.close()
        raise


@APP.route('/')
@APP.route('/<path:path>')
def main(path=''):
    if path == '' or path.endswith('/'):
        return page_explorer(path)
    else:
        return send_file(path)


APP.run(host=CFG.ip, port=CFG.port, debug=SERVER_DEBUG, threaded=True)
