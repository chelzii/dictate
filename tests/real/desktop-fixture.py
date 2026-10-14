import gi,json
from pathlib import Path
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
w=Gtk.Window(title='后台听写桌面验收');w.set_default_size(650,300)
b=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);w.add(b)
b.pack_start(Gtk.Label(label='真实桌面输入框：F9 开始/结束，F8 取消'),False,False,0)
t=Gtk.TextView();b.pack_start(t,True,True,0)
def changed(buf):
 text=buf.get_text(buf.get_start_iter(),buf.get_end_iter(),True)
 Path('/tmp/dictation-desktop-fixture.json').write_text(json.dumps({'text':text},ensure_ascii=False))
t.get_buffer().connect('changed',changed);changed(t.get_buffer())
w.connect('destroy',Gtk.main_quit);w.show_all();t.grab_focus();Gtk.main()
