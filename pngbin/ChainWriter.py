from typing import Iterator, Callable

from . import Writer
from . import EncryptWriter


# ====================================================================================================================
# Use this class to create multiple PngBin image files and write like they are just a single image.
#
# This class uses either Writer or EncryptWriter as a writer class based on `encrypt` parameter.
# This means most of the requirements are going to be the same as those classes.
# One more difference of this class to other 2 writer classes is
# this class will not write anything until the first write(data) method has been called.

# Note: don't forget to call finish() after you're done writing, or use context manager (`with` clause).
# ====================================================================================================================
class ChainWriter:
    def __init__(self, info: Iterator[dict], encrypt: bool = False, on_writer_created: Callable = None):
        """ Creates a writer instance that creates multiple PngBin image files
            and write like they are just a single image.

        :param info:
            An iterator of dict-type, each item must yield with the only keys of `width`, `height`, and `fobj`
            as the same as expected in Writer and EncryptWriter constructor parameters.
            The class will write in order that it yields,
            from first to last, from end of one file to start of next file.
        :param encrypt:
            If True, this class also encrypts the data before each write,
            This means each `info` dict can have an optional `encryptor` key like in EncryptWriter parameter.
        :param on_writer_created:
            If not None and callable, Whenever an underlying writer has been created,
            This callable will be called with that writer instance as an argument.
            This is useful when you want to get `key` and `iv` variables in EncryptWriter instance.
        """
        self._iter_info = info
        self._writer_cls = EncryptWriter if encrypt else Writer
        self._on_writer_created = on_writer_created

        self._is_finished = False
        self._writer = None
        self._wrote = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()
        
        return False

    @property
    def is_finished(self) -> bool:
        return self._is_finished

    def tell(self):
        return self._wrote

    def write(self, data: (bytes, bytearray)) -> int:
        """ Writes input bytes-like object `data` to file.

        :param data: bytes-like object
        :return:
            length in bytes that has been written.
            This is guaranteed to be the same as `len(data)` if underlying `fobj.write(data)` is guaranteed.
        """
        if self._is_finished:
            raise EOFError('This instance is already finished.')

        n = 0
        while n < len(data):
            if self._writer and self._writer.bytes_left > 0:
                n += self._writer.write(data[n:])
            else:
                self._writer = self._get_writer()
        self._wrote += n
        return n

    def finish(self):
        """ Calls `finish()` on the current writer and makes any future `write(data)` calls to raise an EOFError. """
        if self._writer:
            self._writer.finish()
        self._is_finished = True

    def _get_next_info(self) -> dict:
        """ returns the next dict of `info`. """
        try:
            return next(self._iter_info)
        except StopIteration:
            raise EOFError('`info` does not have enough items to create file.')

    def _get_writer(self) -> (Writer, EncryptWriter):
        """ returns Writer or EncryptWriter instance based on `encrypt` constructor parameter.
            also calls on `on_writer_created` with that writer instance if it is a callable."""
        writer = self._writer_cls(**self._get_next_info(), auto_finish=True)
        if callable(self._on_writer_created):
            self._on_writer_created(writer)
        return writer
