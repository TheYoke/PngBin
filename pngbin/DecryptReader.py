import math

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends.openssl import backend as openssl_backend

from . import Reader


# ====================================================================================================================
# Use this class to read an encrypted PngBin image file.
#
# This class is derived from Reader class, So consult Its documentation for parameter details.
# The exception for the parameters are as below:
#   The multiple of `width` and `height` must be divisible by 4.
#   `key` is a bytes-type and must have a length of 32 bytes.
#   `iv` is a bytes-type and must have a length of 16 bytes, If `offset` >= 16, this parameter can be ignored.
#
# Note:
#   The PngBin file must be encrypted with an AES cipher and CBC mode with key length of 256 bits and iv of 128 bits.
# ====================================================================================================================
class DecryptReader(Reader):
    def __init__(self, width: int, height: int, fobj, key: bytes, iv: bytes, offset: int = 0, length: int = 0):
        """ Creates a reader instance for decrypting an encrypted PngBin image file.

        :param key: a bytes-type and must have a length of 32 bytes.
        :param iv: a bytes-type and must have a length of 16 bytes, If `offset` >= 16, this parameter can be ignored.
        """
        if width * height % 4 != 0:
            raise ValueError('The multiple of `width` and `height` must be divisible by 4.')
        if len(key) != 32:
            raise ValueError('Invalid `key` length (Expected: 32 bytes).')
        if offset < 16 and len(iv) != 16:
            raise ValueError('Invalid `iv` length (Expected: 16 bytes).')
        if not 0 <= offset < width * height * 4:
            raise ValueError('offset must have a value between (0 <= offset < width * height * 4).')

        self.__left = (width * height * 4) - offset  # length in bytes that left to be read.
        if 0 < length < self.__left:
            self.__left = length  # uses `length` if it's in a proper range.

        rem = offset % 16  # A block offset remainder.

        # These two block variables below are always divisible by 16.
        block_length = math.ceil((self.__left + rem) / 16) * 16  # Size in bytes the super class is going to read.
        block_offset = offset - rem  # The offset position to the start of a block.

        # Changes the two block variables for retrieving the initialization vector (IV) from previous block.
        if block_offset != 0:
            block_offset -= 16
            block_length += 16

        # Invokes super class constructor with the appropriate offset and length parameters.
        super().__init__(width, height, fobj, block_offset, block_length)

        _iv = iv if offset - rem == 0 else super().read(16)  # Retrieves the IV from previous block if required.
        self._decryptor = Cipher(algorithms.AES(key), modes.CBC(_iv), backend=openssl_backend).decryptor()

        self._block_buffer = bytearray()  # For storing temporary decrypted bytes from a block.
        self.__left += rem  # Adjusts the state for the next line's read method.
        self.read(rem)  # Reads and discards initial decrypted bytes and stores the rest to temporary buffer.

    @property
    def bytes_left(self) -> int:
        """ length in bytes that left to be read. """
        return self.__left

    def read(self, size: int = -1) -> bytes:
        """ reads fobj, decrypts and returns data that contains inside png.

        :param size: if < 0, reads and returns all the left bytes. otherwise, reads `size` bytes and returns.
        :return: bytes object.
        """
        if not 0 <= size <= self.__left:
            size = self.__left  # if out of range, changes the `size` value to read all that left.
        buffer = bytearray()
        while len(buffer) < size:
            n = size - len(buffer)
            if self._block_buffer:  # Appends bytes that left in the block buffer first.
                n = min(n, len(self._block_buffer))
                buffer.extend(self._block_buffer[:n])
                del self._block_buffer[:n]
            else:
                m = (math.ceil(n / 16) * 16) - n  # A block size complementary (m+n is always divisible by 16).
                blocks = self._decryptor.update(super().read(n + m))  # reads and decrypts in blocks.
                if m > 0:
                    buffer.extend(blocks[:n])  # Appends `n` bytes to `buffer` ...
                    self._block_buffer.extend(blocks[n:])  # ... And puts the rest (`m` bytes) to temp. block buffer.
                else:
                    buffer.extend(blocks)
            self.__left -= n
        return bytes(buffer)
