from typing import (
    Callable,
    Dict,
    IO,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import httpx

MIN_BUFFER_SIZE = 64 * 2**10  # 64KiB
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0'

FileContent = Union[IO[str], IO[bytes], str, bytes]
FileTypes = Union[
    # file (or text)
    FileContent,
    # (filename, file (or text))
    Tuple[Optional[str], FileContent],
    # (filename, file (or text), content_type)
    Tuple[Optional[str], FileContent, Optional[str]],
]
RequestFiles = Union[Mapping[str, FileTypes], Sequence[Tuple[str, FileTypes]]]


class Uploader:
    def __init__(self, method: str, url: str, **client_kwargs):
        """ An uploader superclass with optional progress callback.

        :param method: A http method for uploading.
        :param url: A url for uploading.
        :param client_kwargs: Pass optional keyword arguments to httpx.Client.
        """
        self.method = method
        self.url = url

        headers = {'User-Agent': USER_AGENT}
        if 'headers' in client_kwargs:
            headers.update(client_kwargs['headers'])
            del client_kwargs['headers']
        self.client = httpx.Client(headers=headers, **client_kwargs)

    @staticmethod
    def progress_callback(bytes_read: int, bytes_total: int) -> None:
        """ Subclass can optionally overwrite this to make a progress output.
            This will be called just before each buffer has been sent.

        :param bytes_read: Number of bytes this class has read so far.
        :param bytes_total: Number of total bytes to send.
        """
        pass

    def upload(self, data: dict, files: RequestFiles, **request_kwargs) -> httpx.Response:
        """ Start file upload to server.

        :param data: A mapping data to send.
        :param files: A mapping file to send.
        :param request_kwargs: Pass optional keyword arguments to client.build_request.
        :return: A response of type httpx.Response.
        """
        request = self.client.build_request(
            self.method, self.url,
            data=data, files=files,
            **request_kwargs
        )
        bytes_total = int(request.headers['Content-Length'])
        request.stream = StreamMonitor(
            BufferedStream(request.stream, MIN_BUFFER_SIZE),
            lambda bytes_read: self.progress_callback(bytes_read, bytes_total)
        )
        return self.client.send(request)

    def upload_file(self, path: str) -> Tuple[str, Dict[str, str]]:
        """ Subclass should implement this method as a wrapper of `upload()`.

        :param path: A path to a file you want to upload.
        :return: a tuple of (image_url, extra)
        """
        raise NotImplementedError


class SimpleProgress:
    @staticmethod
    def progress_callback(bytes_read: int, bytes_total: int) -> None:
        n = len(str(bytes_total))
        print(f'{bytes_read:>{n}}/{bytes_total} {bytes_read / bytes_total:.2%}', end='\r')


class StreamMonitor:
    def __init__(self, stream: Iterable[bytes], callback: Callable):
        self.stream = stream
        self.callback = callback
        self.bytes_read = 0

    def __iter__(self) -> bytes:
        for chunk in self.stream:
            self.bytes_read += len(chunk)
            self.callback(self.bytes_read)
            yield chunk


class BufferedStream:
    def __init__(self, stream: Iterable[bytes], min_size: int):
        self.stream = stream
        self.min_size = min_size

    def __iter__(self) -> bytes:
        chunks = bytearray()
        for chunk in self.stream:
            chunks.extend(chunk)
            if len(chunks) >= self.min_size:
                yield bytes(chunks)
                chunks.clear()
        yield bytes(chunks)
