from pngbin import ChainReader

import flask
import requests

import sqlite3
import argparse
import html
import sys
import os
import io


ITEMS_PER_ROW = 5
ITEMS_PER_PAGE = 15  # should be a multiple of `ITEMS_PER_ROW`
SERVER_DEBUG = False  # if True, run server in debug mode.

WEB_TITLE = 'PngBin Movies'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0'
APP = flask.Flask(__name__, static_url_path='/__static__')


def _get_args(argv):
    args = (
        {
            'description': 'Startup a local server for PngBin Movies.'
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
                ['--movies_db', '-v'],
                {
                    'default': 'movies.db',
                    'help': 'An sqlite database file contains movies info. (default: movies.db)'
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
assert os.path.isfile(CFG.movies_db), f'Database file "{CFG.movies_db}" does not exist.'


def _get_result_html(rows):
    lines = []
    i = -1
    for i, row in enumerate(rows):
        if i % ITEMS_PER_ROW == 0:
            lines.append('<div class="row p-2">')

        path, title, year = [html.escape(str(x)) for x in row]
        lines.append('<div class="col text-center p-0">')
        lines.append('<div class="container pl-2 pr-2 img-container">')
        lines.append(f'<a href="/f/{path}">')
        lines.append(f'<img src="/t/{path}" class="img-thumbnail p-0">')
        lines.append('</a>')
        lines.append('</div>')
        lines.append(f'<p class="text-center mb-3"><strong>{title} ({year})</strong></p>')
        lines.append('</div>')

        if i % ITEMS_PER_ROW == ITEMS_PER_ROW - 1:
            lines.append('</div>')

    if i >= 0 and i % ITEMS_PER_ROW != ITEMS_PER_ROW - 1:
        lines.append('</div>')

    return '\n'.join(lines)


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


@APP.route('/')
def page_home():
    cur = _get_conn(CFG.movies_db).cursor()
    cur.execute('SELECT path, title, year '
                'FROM movies '
                'ORDER BY RANDOM() '
                f'LIMIT {ITEMS_PER_PAGE};')
    result_html = _get_result_html(cur)

    return flask.render_template('movies.html', **{
        'page_title': WEB_TITLE,
        'result_text': 'Random Movies',
        'result_html': result_html,
        'search_query': '',
        'pagination': {}
    })


@APP.route('/search')
def page_search():
    query = flask.request.args.get('q', '').strip()
    page = flask.request.args.get('p', '').strip()

    _query = '%' + query.replace(' ', '%') + '%'
    page = int(page) if page.isdigit() else 1
    offset = ITEMS_PER_PAGE * (page - 1)

    cur = _get_conn(CFG.movies_db).cursor()
    if query:
        result_text = f'Search result of "{query}". '
        cur.execute('SELECT path, title, year '
                    'FROM movies '
                    'WHERE path LIKE ? '
                    'ORDER BY year DESC, path ASC '
                    f'LIMIT {ITEMS_PER_PAGE} OFFSET ?;',
                    (_query, offset))
    else:
        result_text = 'Search all movies. '
        cur.execute('SELECT path, title, year '
                    'FROM movies '
                    'ORDER BY year DESC, path ASC '
                    f'LIMIT {ITEMS_PER_PAGE} OFFSET ?;',
                    (offset,))
    result_html = _get_result_html(cur)

    if query:
        cur.execute('SELECT COUNT() '
                    'FROM movies '
                    'WHERE path LIKE ?;',
                    (_query,))
    else:
        cur.execute('SELECT COUNT() '
                    'FROM movies;')
    total = cur.fetchone()[0]

    result_text += f'Found {total} results' if total else 'NOT FOUND!'
    return flask.render_template('movies.html', **{
        'page_title': WEB_TITLE + ' | ' + result_text,
        'result_text': result_text,
        'result_html': result_html,
        'search_query': query,
        'pagination': {'page': page, 'total': total, 'items_per_page': ITEMS_PER_PAGE}
    })


@APP.route('/t/<string:path>')
def send_thumbnail(path):
    cur = _get_conn(CFG.movies_db).cursor()
    cur.execute('SELECT thumbnail FROM movies WHERE path = ?;', (path,))
    data = cur.fetchone()
    if data is None:
        flask.abort(404)

    data = io.BytesIO(data[0])
    return flask.send_file(data, mimetype='image/jpeg', last_modified=os.stat(CFG.movies_db).st_mtime)


@APP.route('/f/<string:path>')
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
        if length > 0:
            reader = ChainReader(_get_info(cur, images_id), first, length, decrypt=True, auto_close=True)
        else:
            reader = io.BytesIO()

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


APP.run(host=CFG.ip, port=CFG.port, debug=SERVER_DEBUG, threaded=True)
