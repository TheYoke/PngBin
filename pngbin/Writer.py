import math
import zlib


# ====================================================================================================================
# Use this class to create a PngBin image file and write any data to it.
#
# The result png file format will have only 1 IDAT chunk wth max length of 4,294,967,295 (2**32-1).
# Its color type is RGBA (includes alpha channel).
# The amount of data that can be contained inside png file is the result of 4 x width x height bytes.
# Each zlib chunk has a length of 65,535 (2**16-1) bytes, except for the last chunk which can have arbitrary size.
# No compression nor filter methods are applied.

# Note: don't forget to call finish() after you're done writing, or use context manager (`with` clause).
# Reference: http://www.libpng.org/pub/png/spec/1.2/png-1.2-pdg.html
# ====================================================================================================================
class Writer:
    def __init__(self, width: int, height: int, fobj, auto_finish: bool = False):
        """ Creates a PngBin writer instance.

        :param width: the width of png (0 < width < 2**32).
        :param height: the height of png (0 < height < 2**32).
        :param fobj: file-like object that has write(data) method.
        :param auto_finish: if True, the instance automatically calls finish() when write(data) method
                            detects the last bytes have been written.
        """
        if not 0 < width < 2**32:
            raise ValueError('width must have a value between (0 < width < 2**32).')
        if not 0 < height < 2**32:
            raise ValueError('height must have a value between (0 < height < 2**32).')
        if not hasattr(fobj, 'write'):
            raise AttributeError('fobj must has a write(data) attribute.')

        self._width, self._height = width, height
        self._fobj = fobj
        self._auto_finish = auto_finish

        self._idat_len = self._calc_idat_len(self._width, self._height)
        if self._idat_len >= 2**32:
            raise ValueError('the result of IDAT length cannot be greater than nor equal to 2**32')

        self._left = self._width * self._height * 4  # length in bytes that can be written to.
        self._leftf = self._left + self._height  # same as above but includes filter bytes.
        self._nextf = 0  # countdown number to the next filter byte.
        self._crc32 = 0  # initial value of CRC32.
        self._adler32 = 1  # initial value of Adler32.
        self._is_finished = False  # True if the png footer has already been written.
        self._buffer = bytearray()  # buffer that holds data of each zlib chunk. (max length of 65535)

        self._write_head()  # starts writing header.

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()
        return False

    @staticmethod
    def _calc_idat_len(width: int, height: int) -> int:
        """ Calculates and returns the length in bytes that IDAT is going to have. """
        a = width * height * 4
        b = a + height
        c = b / 0xffff
        d = math.ceil(c)
        e = d * 5
        return 2 + e + b + 4

    @property
    def is_finished(self) -> bool:
        return self._is_finished

    @property
    def bytes_left(self) -> int:
        return self._left

    @property
    def result_length(self) -> int:
        """ Returns the length in bytes of the output png file is going to have. """
        #  header +       IDAT     + footer
        return 41 + self._idat_len + 16

    def tell(self):
        return self._width * self._height * 4 - self._left

    def write(self, data: (bytes, bytearray)) -> int:
        """ Writes input bytes-like object `data` to buffer.
        Note: if there is no space left in this image (`bytes_left` returns 0),
              the rest of this function's call will be no-op and returns 0, unless `auto_finish` is True.

        :param data: bytes-like object
        :return:
            length in bytes that has been written.
            This is guaranteed to be the same as `len(data)` if underlying `fobj.write(data)` is guaranteed,
            unless `bytes_left` is 0 after the call.
        """
        if self._is_finished:
            raise EOFError('`fobj` is already finished.')
        do = 0
        dl = len(data)
        while self._left > 0 and do < dl:
            if len(self._buffer) == 0xffff:
                self._flush_buffer()
            if self._nextf == 0:
                self._buffer.append(0)  # append a filter byte.
                self._nextf = self._width * 4
            n = min(dl - do, 0xffff - len(self._buffer), self._nextf, self._left)
            self._buffer.extend(data[do:do+n])
            do += n
            self._nextf -= n
            self._left -= n
        if self._left == 0 and self._auto_finish:
            self.finish()
        return do

    def finish(self) -> bool:
        """ Flushes remaining buffer and finishes the writing with a footer.
            If there is space left that can be written (`bytes_left` > 0), fills the rest with null-bytes (\x00).
            Note that this method will NOT close the `fobj` for you, call close() instead if you want to do that.

        :return: False if object is already finished, otherwise True.
        """
        if not self._is_finished:
            self._auto_finish = False
            while self._left > 0:
                n = min(2**20, self._left)  # 1MiB max buffer size.
                self.write(bytes(n))
            self._flush_buffer()
            self._write_foot()
            self._is_finished = True
            return True
        else:
            return False

    def close(self):
        """ Calls finish() and then calls close() on `fobj` if it has one. """
        self.finish()
        if hasattr(self._fobj, 'close'):
            self._fobj.close()

    def _flush_buffer(self):
        """ Writes a chunk into fobj. """
        n = len(self._buffer)
        if self._leftf > 0xffff:
            b = b'\x00\xff\xff\x00\x00'  # first byte indicates that this chunk is NOT the last chunk.
        else:
            x = n.to_bytes(2, 'little')  # chunk size in bytes.
            y = (0xffff - n).to_bytes(2, 'little')  # the above is subtracted by 65535.
            b = b'\x01' + x + y  # first byte indicates that this chunk IS the last chunk.
        self._crc32 = zlib.crc32(b, self._crc32)  # updates CRC32.
        self._crc32 = zlib.crc32(self._buffer, self._crc32)
        self._adler32 = zlib.adler32(self._buffer, self._adler32)  # updates Adler32.
        self._fobj.write(b)  # writes to underlying file-object.
        self._fobj.write(self._buffer)  # writes to underlying file-object.
        del self._buffer[:]  # clear the buffer.
        self._leftf -= n

    def _write_head(self):
        self._fobj.write(b'\x89PNG\r\n\x1a\n')  # PNG magic header.
        self._fobj.write(b'\x00\x00\x00\x0d')  # fixed length of IHDR chunk (13).
        b = bytearray()
        b.extend(b'IHDR')
        b.extend(self._width.to_bytes(4, 'big'))  # integer of width in bytes.
        b.extend(self._height.to_bytes(4, 'big'))  # integer of height in bytes.
        b.extend(b'\x08\x06\x00\x00\x00')  # Bit_Depth, Color_Type, Compression_Method, Filter_Method, Interlace_Method
        c = zlib.crc32(b)
        self._fobj.write(b + c.to_bytes(4, 'big'))  # writes data and crc32.
        self._fobj.write(self._idat_len.to_bytes(4, 'big'))  # writes length of idat in bytes.
        b = b'IDATx\x01'  # IDAT name and 2-byte zlib header.
        self._crc32 = zlib.crc32(b, self._crc32)  # updates crc32.
        self._fobj.write(b)

    def _write_foot(self):
        adler32 = self._adler32.to_bytes(4, 'big')
        self._crc32 = zlib.crc32(adler32, self._crc32)
        crc32 = self._crc32.to_bytes(4, 'big')
        footer = b'\x00\x00\x00\x00IEND\xaeB`\x82'
        self._fobj.write(adler32 + crc32 + footer)
