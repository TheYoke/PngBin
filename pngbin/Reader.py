import math
import struct
from typing import Tuple, Union


# ====================================================================================================================
# Use this class to read data from a PngBin image file.
# It has an ability to seek to an arbitrary offset of data in the image file.
#
# Terminology:
#   data-offset = A zero-based index offset of the data that contains inside a PngBin file.
#                 Maximum offset is the value of 4 x width x height - 1.
#   png-offset = A zero-based index offset of the whole png file.
#                Maximum offset is the length in bytes of png file subtracts by 1.
# ====================================================================================================================
class Reader:
    def __init__(self, width: int, height: int, fobj, offset: int = 0, length: int = 0):
        """ Creates a PngBin reader instance with offset seeking capability.

        :param width: width of the PngBin image.
        :param height: height of the PngBin image.
        :param fobj:
            if callable:
                It will be called with two png-offset arguments,
                    `first_offset`:
                        The first byte offset this class is going to read.
                    `last_offset` (inclusive):
                        The last byte offset this class is going to read.
                It must return a file-like object that has read(size) method attribute
                with the current read position value of `first_offset`.
            if not callable:
                It has to be a seekable file-like object that has read(size) and seek(pos) method attributes.
        :param offset: data-offset of the PngBin image.
        :param length: length in bytes to read. if length < 1, reads to the end of file.
        """
        if not 0 < width < 2**32:
            raise ValueError('width must have a value between (0 < width < 2**32).')
        if not 0 < height < 2**32:
            raise ValueError('height must have a value between (0 < height < 2**32).')

        if not 0 <= offset < width * height * 4:
            raise ValueError('offset must have a value between (0 <= offset < width * height * 4).')

        self._width, self._height = width, height

        self._left = (self._width * self._height * 4) - offset  # length in bytes that left to be read.
        if 0 < length < self._left:
            self._left = length  # uses `length` if it's in a proper range.

        p_offset, self._nextf, self._nextz = self._convert_offset(self._width, offset, True)
        p_offset_l = self._convert_offset(self._width, (offset + self._left) - 1)  # last png-offset (inclusive).

        self._nextf -= p_offset  # countdown for next filter byte.
        self._nextz -= p_offset  # countdown for next zlib header.

        if callable(fobj):
            self._fobj = fobj(p_offset, p_offset_l)
            if not hasattr(self._fobj, 'read'):
                raise AttributeError('`fobj` must return file-like object that has read method attribute.')
        elif hasattr(fobj, 'read') and hasattr(fobj, 'seek'):
            self._fobj = fobj
            self._fobj.seek(p_offset, 0)
        else:
            raise AttributeError('`fobj` must be callable or file-like object '
                                 'that has read and seek method attributes.')

    @property
    def bytes_left(self) -> int:
        """ length in bytes that left to be read. """
        return self._left

    def read(self, size: int = -1) -> bytes:
        """ reads `fobj` and return data that contains inside png.

        :param size: if < 0, reads and returns all the left bytes. otherwise, reads `size` bytes and returns.
        :return: bytes object.
        """
        if not 0 <= size <= self._left:
            size = self._left  # if out of range, changes the `size` value to read all that left.
        buffer = bytearray()
        while len(buffer) < size:
            n = min(size - len(buffer), self._nextf, self._nextz)
            c = self._fobj.read(n)
            if len(c) != n:
                raise IncompleteRead(
                    f'The length of returning bytes is not equal to what requested. (Expected: {n}, Got: {len(c)})'
                )
            buffer.extend(c)
            self._left -= n   # \
            self._nextf -= n  # -> counting down the 3 variables.
            self._nextz -= n  # /
            if self._left > 0:  # no need to do anything else if there's nothing left.
                if self._nextz == 0:
                    self._read_zlib()
                    self._nextf -= 5  # counting down filter byte.
                    self._nextz = 0xffff  # resets countdown for next zlib header.
                elif self._nextf == 0:
                    if self._fobj.read(1) != b'\x00':
                        raise InvalidPngError('Invalid Filter detected.')
                    self._nextz -= 1  # counting down next zlib header.
                    self._nextf = self._width * 4  # resets countdown for next filter byte.
                    if self._nextf >= self._nextz:  # checks and adds that if zlib header bytes are in the way.
                        self._nextf += math.ceil(self._nextf / 0xffff) * 5
        return bytes(buffer)  # converts to bytes object before returns.

    def close(self):
        """ Calls close() on `fobj` if it has one. """
        if hasattr(self._fobj, 'close'):
            self._fobj.close()

    def _read_zlib(self):
        """ Reads and verifies zlib chunk header for length of 5 bytes.
            if failed, raises InvalidPngError. """
        x, y, z = struct.unpack('<BHH', self._fobj.read(5))
        if x not in [0, 1] or y + z != 0xffff:
            raise InvalidPngError('Invalid zlib detected')

    @staticmethod
    def _convert_offset(width: int, offset: int, extra: bool = False) -> Union[Tuple[int, int, int], int]:
        """ Converts data-offset to png-offset.

        :param width: width of PngBin image.
        :param offset: data-offset of PngBin.
        :param extra: if true, returns tuple of 3 values:
                      (png_offset, next_filter_offset, next_zlib_header_offset)
        :return: if extra is False, returns only converted png-offset
        """
        r = (width * 4)  # number of bytes in a row.
        f = (offset // r) + 1  # number of filter bytes that comes before offset.
        o = offset + f  # offset includes filter bytes.
        c = (o // 0xffff) + 1  # number of zlib chunk headers that comes before offset.
        c *= 5  # each zlib chunk header has length of 5 bytes.
        h = 41 + 2  # fixed header size + zlib main header size.
        p = h + c + o  # converted png-offset.
        if extra:
            nf = r - (offset % r)  # number of bytes from offset until next filter byte.
            nz = 0xffff - (o % 0xffff)  # number of bytes from offset until next zlib header.
            if nf >= nz:  # checks and adds that if zlib header bytes are in the way.
                nf += math.ceil(nf / 0xffff) * 5
            return p, p + nf, p + nz
        else:
            return p


class InvalidPngError(Exception):
    """ Raises when Reader detects an invalid data in a PngBin file.
        This usually means that the image is not created by PngBin. """
    pass


class IncompleteRead(Exception):
    """ Raises when Reader's fobj returns bytes which its length is not equal to what requested. """
    pass
