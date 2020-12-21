import itertools
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
            timeout=Timeout(5.0, read=60.0),
            cookies={
                'sa': cookie_sa,
                'cookie_session': cookie_session
            }
        )

        self.last_response = self.client.get('https://www.flickr.com/photos/upload')
        auth_hash = re.search(r'"auth_hash":"([0-9a-f]{64})"', self.last_response.text)
        api_key = re.search(r'"api_key":"([0-9a-f]{32})"', self.last_response.text)
        user_id = re.search(r'"nsid":"([\w@]+)"', self.last_response.text)
        assert auth_hash and api_key and user_id, 'Incorrect Cookies info?'
        self.auth_hash, self.api_key, self.user_id = auth_hash[1], api_key[1], user_id[1]

    def _request_api(self, data):
        headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
        self.last_response = self.client.post('https://api.flickr.com/services/rest', headers=headers, data=data)

        result = json.loads(self.last_response.text)
        assert result['stat'] == 'ok', self.last_response.text

        return result

    def get_image_url_by_photo_id(self, photo_id):
        data = {
            'photo_id': photo_id,
            'method': 'flickr.photos.getInfo',
            'format': 'json',
            'nojsoncallback': 1,
            'auth_hash': self.auth_hash,
            'api_key': self.api_key
        }

        return 'https://live.staticflickr.com/%(server)s/%(id)s_%(originalsecret)s_o.%(originalformat)s' \
               % self._request_api(data)["photo"]

    def get_image_url_by_latest(self, name):
        data = {
            'method': 'flickr.people.getPhotos',
            'format': 'json',
            'nojsoncallback': '1',
            'auth_hash': self.auth_hash,
            'api_key': self.api_key,
            'user_id': self.user_id,
            'per_page': '1',
            'page': '1',
            'extras': 'url_o',
        }

        photo = self._request_api(data)['photos']['photo'][0]
        assert photo['title'] == name, photo['title']

        return photo['url_o']

    def get_image_url_by_titles(self, *titles):
        title_urls = {}
        for page in itertools.count(1):
            data = {
                'method': 'flickr.people.getPhotos',
                'format': 'json',
                'nojsoncallback': '1',
                'auth_hash': self.auth_hash,
                'api_key': self.api_key,
                'user_id': self.user_id,
                'per_page': '500',
                'page': page,
                'extras': 'url_o',
            }

            photos = self._request_api(data)['photos']
            for photo in photos['photo']:
                title_urls[photo['title']] = photo['url_o']

            if page == photos['pages']:
                break

        return [(title, title_urls[title]) for title in titles]

    def upload_file(self, path: str) -> Tuple[str, Dict[str, str]]:
        data = {
            'auth_hash': self.auth_hash,
            'api_key': self.api_key,
            'hidden': '2'  # hide from public searches.
        }

        filename = os.path.split(path)[1]
        with open(path, 'rb') as fobj:
            self.last_response = self.upload(
                data=data, files={
                    'photo': (filename, fobj)
                }
            )

        if self.last_response.status_code == 504:
            name = os.path.splitext(filename)[0]
            return self.get_image_url_by_latest(name), {}
        else:
            xml = ElementTree.fromstring(self.last_response.text)
            assert xml.attrib['stat'] == 'ok', self.last_response.text
            return self.get_image_url_by_photo_id(xml[0].text), {}
