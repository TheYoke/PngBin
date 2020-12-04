import json
import os
import re
from typing import Tuple, Dict
from xml.etree import ElementTree

from httpx import Timeout

from .Uploader import SimpleProgress, Uploader


class Flickr(SimpleProgress, Uploader):
    def __init__(self, cookie_sa, cookie_session):
        super().__init__(
            'POST', 'https://up.flickr.com/services/upload',
            timeout=Timeout(5.0, read=90.0),
            cookies={
                'sa': cookie_sa,
                'cookie_session': cookie_session
            }
        )

        response = self.client.get('https://www.flickr.com/photos/upload')
        auth_hash = re.search(r'"auth_hash":"([0-9a-f]{64})"', response.text)
        api_key = re.search(r'"api_key":"([0-9a-f]{32})"', response.text)
        assert auth_hash and api_key, 'Incorrect Cookies info?'
        self.auth_hash, self.api_key = auth_hash[1], api_key[1]

    def upload_file(self, path: str) -> Tuple[str, Dict[str, str]]:
        data = {
            'auth_hash': self.auth_hash,
            'api_key': self.api_key,
            'hidden': '2'  # hide from public searches.
        }
        with open(path, 'rb') as fobj:
            response = self.upload(
                data=data, files={
                    'photo': (os.path.split(path)[1], fobj)
                }
            )

        xml = ElementTree.fromstring(response.text)
        assert xml.attrib['stat'] == 'ok', response.text

        data = {
            'photo_id': xml[0].text,
            'method': 'flickr.photos.getInfo',
            'format': 'json',
            'nojsoncallback': 1,
            'auth_hash': self.auth_hash,
            'api_key': self.api_key
        }

        headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
        response = self.client.post('https://api.flickr.com/services/rest', headers=headers, data=data)

        result = json.loads(response.text)
        assert result['stat'] == 'ok', response.text

        image_url = f'https://live.staticflickr.com/%s/%s_%s_o.%s' % (
            result["photo"]["server"],
            result["photo"]["id"],
            result["photo"]["originalsecret"],
            result["photo"]["originalformat"]
        )

        return image_url, {}
