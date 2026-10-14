from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write('''<!doctype html><meta charset="utf-8"><title>后台听写浏览器验收</title><h1>F9 / F8 网页输入验收</h1><textarea autofocus style="width:90%;height:150px"></textarea><script>const e=document.querySelector('textarea');function report(){fetch('/report',{method:'POST',body:JSON.stringify({text:e.value,focused:document.hasFocus()})})}e.addEventListener('input',report);report()</script>'''.encode())
 def do_POST(self):
  Path('/tmp/dictation-browser-fixture.json').write_bytes(self.rfile.read(int(self.headers['Content-Length'])));self.send_response(204);self.end_headers()
 def log_message(self,*args):pass
HTTPServer(('127.0.0.1',18769),Handler).serve_forever()
