import os
import redis
import urllib.parse
from datetime import datetime
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.wsgi import SharedDataMiddleware
from werkzeug.utils import redirect
from jinja2 import Environment, FileSystemLoader

def base36_encode(number):
    assert number >= 0, 'positive integer required'
    if number == 0:
        return '0'
    base36 = []
    while number != 0:
        number, i = divmod(number, 36)
        base36.append('0123456789abcdefghijklmnopqrstuvwxyz'[i])
    return ''.join(reversed(base36))


class Board(object):

    def __init__(self, config):
        self.redis = redis.Redis(config['redis_host'], config['redis_port'])
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(loader=FileSystemLoader(template_path), autoescape=True)
        self.url_map = Map([
            Rule('/', endpoint='boards'),
            Rule('/<board_id>', endpoint='view_board'),
            Rule('/new', endpoint='new_board'),
            Rule('/<board_id>/add_comment', endpoint='add_comment')
            ])

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype='text/html')    


    def dispatch_request(self, request):
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            return getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            return e
	

    def on_boards(self, request):
        boards = {}
        for key in self.redis.keys("board:*"):
            board_id = key[6:].decode('utf-8')
            val = self.redis.get(key).decode('utf-8')
            boards[board_id] = val
        return self.render_template('index.html', boards = boards)

    def on_new_board(self, request):
        error = None
        creator = ''
        board_name=''
        if request.method == 'POST':
            creator = request.form['username']
            board_name = request.form['board_name']
            
            if len(creator) > 30:
                error = 'User name must be max 30 symbols'
            
            elif len(board_name) > 50:
                error = 'Board name max symbols is 50'

            else:
                board_id = self.new_board(creator, board_name)
                return redirect('/%s' % board_id)
        return self.render_template('new_board.html', error=error, creator = creator, board_name = board_name)           

    def new_board(self, creator, board_name):
        current_date = datetime.now()
        board_id = self.redis.get('board:' + board_name)
        if board_id is not None:
            return board_id
        board_num = self.redis.incr('last-board-id')
        board_id = base36_encode(board_num)
          
        self.redis.set('board:' + board_id, board_name)
        self.redis.set('creator:board:' + board_id, creator)
        self.redis.set('create_date:board:' + board_id, current_date)

        return board_id

    def on_view_board(self, request, board_id):
        board_name = self.redis.get('board:' + board_id).decode('utf-8')
        creator = self.redis.get('creator:board:' + board_id).decode('utf-8')
        create_date = self.redis.get('create_date:board:' + board_id).decode('utf-8')
        comments = []
        for key in self.redis.keys("comment:*:board:" + board_id):
            key = key.decode('utf-8')
            text = self.redis.get(key).decode('utf-8')
            username = self.redis.get("username:" + key).decode('utf-8')
            comments.append([username, text])

        return self.render_template('view_board.html',
            board_id=board_id, 
            board_name=board_name,
            creator=creator,
            create_date=create_date,
            comments=comments)

    def on_add_comment(self, request, board_id):
        error = None
        username = ''
        text=''
        if request.method == 'POST':
            username = request.form['username']
            text = request.form['comment_text']
            if len(username) > 30:
                error = "User name must be max 30 symbol"
            elif len(username) > 255:
                error = "Length of comments maximum 255 symbol"
            else:
                self.new_comment(username, text, board_id)
                return redirect('/%s' % board_id)
        return self.render_template('add_comment.html', error=error, username = username, text = text)                        
   	
    def new_comment(self, username, text, board_id):
        comment_num = self.redis.incr('last-comment-id:board:' + board_id)
        comment_id = base36_encode(comment_num)
        self.redis.set('comment:' + comment_id + ':board:' + board_id, text)
        self.redis.set('username:comment:' + comment_id + ':board:' + board_id, username)  

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)



def create_app(redis_host='localhost', redis_port=6379, with_static=True):
    app = Board({
        'redis_host':       redis_host,
        'redis_port':       redis_port
    })
    if with_static:
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
            '/static':  os.path.join(os.path.dirname(__file__), 'static')
        })
    return app

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    app = create_app()
run_simple('127.0.0.1', 5000, app, use_debugger=True, use_reloader=True)