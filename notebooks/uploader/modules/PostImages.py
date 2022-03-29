import os
import re
import secrets
import string
import time
from typing import Tuple, Dict

from httpx import Timeout

from .Uploader import Uploader, SimpleProgress

ALPHABET = string.ascii_letters + string.digits


class PostImages(SimpleProgress, Uploader):
    def __init__(self):
        super().__init__(
            'POST', 'https://postimages.org/json/rr',
            timeout=Timeout(5.0, read=10.0)
        )

        response = self.client.get('https://postimages.org')
        self.token = re.search('"token","(.+?)"', response.text)[1]

    def delete(self, private_url: str) -> dict:
        response = self.client.get(private_url)
        if response.status_code == 404:
            return {}  # This image does not exist.

        m = re.search(r'data-remove="(\w+)" data-hash="(\w+)"', response.text)
        data = {'image': m[1], 'hash': m[2]}
        response = self.client.request('DELETE', 'https://postimg.cc/json', data=data)
        return response.json()

    def upload_file(self, path: str) -> Tuple[str, Dict[str, str]]:
        data = {
            'token': self.token,
            'upload_session': ''.join(secrets.choice(ALPHABET) for _ in range(32)),
            'numfiles': '1',
            'optsize': '0',
            'session_upload': str(int(time.time())),
            'gallery': '',
            'expire': '0',
        }
        headers = {
            'Accept': 'application/json'
        }
        with open(path, 'rb') as fobj:
            response = self.upload(
                data=data, files={
                    'file': (os.path.split(path)[1], fobj)
                }, headers=headers
            )

        result = response.json()
        assert result['status'] == 'OK', result

        response = self.client.get(result['url'])
        m = re.search(r'>Removal link:.+?value="(https?://.+?)"', response.text)
        removal_link = m[1]

        m = re.search(r'>Link:.+?value="(https?://.+?)"', response.text)
        response = self.client.get(m[1])
        m = re.search(r'"(https://i\.postimg\.cc/.+?)\?dl=1"', response.text)
        image_url = m[1]

        return image_url, {'removal_link': removal_link}
