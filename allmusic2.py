#!/usr/bin/env python3
"""AllMusic 2.0 - Native desktop mini app."""
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gst, GLib, GdkPixbuf, Gdk, Pango
import requests
import json
import os
import threading
import sys
import time
import signal
import subprocess
from io import BytesIO

APP_NAME = 'AllMusic 2.0'
APP_SLUG = 'allmusic2'

CFG_DIR = os.path.expanduser(f'~/.config/{APP_SLUG}')
CFG_FILE = os.path.join(CFG_DIR, 'config.json')
SOCKET_PATH = os.path.join(CFG_DIR, 'app.sock')

def _load_env():
    global API_BASE, DL_DIR
    cfg = {}
    try:
        if os.path.exists(CFG_FILE):
            with open(CFG_FILE) as f:
                cfg = json.load(f)
    except:
        pass
    API_BASE = os.environ.get('ALLMUSIC_API_BASE') or cfg.get('api_base', 'https://edgemarketing.art/allmusic')
    DL_DIR = cfg.get('dl_dir', os.path.expanduser('~/Descargas'))

_load_env()

WIDTH = 420
HEIGHT = 640
Gst.init(None)

class ThumbLoader:
    HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

    def __init__(self, size=(48, 48)):
        self.size = size
        self.cache = {}

    def get(self, url, callback):
        if url in self.cache:
            pix = self.cache[url]
            if pix:
                GLib.idle_add(callback, pix)
            return

        def load():
            pix = None
            for attempt_url in [url, url.replace('hqdefault', 'mqdefault'), url.replace('hqdefault', 'default')]:
                try:
                    r = requests.get(attempt_url, headers=self.HEADERS, timeout=8)
                    if r.status_code == 200 and len(r.content) > 100:
                        tmp = '/tmp/am_thumb_' + str(hash(attempt_url)) + '.jpg'
                        with open(tmp, 'wb') as f:
                            f.write(r.content)
                        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(tmp, self.size[0], self.size[1], True)
                        try: os.remove(tmp)
                        except: pass
                        break
                except:
                    continue
            self.cache[url] = pix
            if pix:
                GLib.idle_add(callback, pix)
        threading.Thread(target=load, daemon=True).start()

class PlayerBar(Gtk.Box):
    def __init__(self, player):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.player = player
        self._updating = False
        self.set_name('player-bar')

        art_box = Gtk.Box(spacing=8)
        art_box.set_name('player-art-box')
        self.art = Gtk.Image()
        self.art.set_size_request(48, 48)
        self.art.set_name('player-art')
        self.art.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.title_lbl = Gtk.Label(label=APP_NAME)
        self.title_lbl.set_name('player-title')
        self.title_lbl.set_halign(Gtk.Align.START)
        self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_lbl = Gtk.Label(label='Listo')
        self.artist_lbl.set_name('player-artist')
        self.artist_lbl.set_halign(Gtk.Align.START)
        self.artist_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_box.pack_start(self.title_lbl, False, False, 0)
        info_box.pack_start(self.artist_lbl, False, False, 0)

        art_box.pack_start(self.art, False, False, 4)
        art_box.pack_start(info_box, True, True, 4)
        self.pack_start(art_box, False, False, 0)

        prog_box = Gtk.Box(spacing=6)
        prog_box.set_name('prog-box')
        self.time_lbl = Gtk.Label(label='0:00')
        self.time_lbl.set_name('time-lbl')
        self.prog = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.5)
        self.prog.set_size_request(-1, 8)
        self.prog.set_slider_size_fixed(False)
        self.prog.set_draw_value(False)
        self.prog.set_name('prog-slider')
        self.prog.connect('button-release-event', self.on_seek)
        self.dur_lbl = Gtk.Label(label='0:00')
        self.dur_lbl.set_name('time-lbl')
        prog_box.pack_start(self.time_lbl, False, False, 0)
        prog_box.pack_start(self.prog, True, True, 0)
        prog_box.pack_start(self.dur_lbl, False, False, 0)
        self.pack_start(prog_box, False, False, 2)

        ctrl_box = Gtk.Box(spacing=10)
        ctrl_box.set_name('ctrl-box')
        ctrl_box.set_halign(Gtk.Align.CENTER)
        self.prev_btn = Gtk.Button(label='⏮')
        self.prev_btn.set_name('ctrl-btn')
        self.prev_btn.connect('clicked', lambda w: self.player.prev())
        self.play_btn = Gtk.Button(label='▶')
        self.play_btn.set_name('ctrl-btn-play')
        self.play_btn.connect('clicked', lambda w: self.player.toggle())
        self.next_btn = Gtk.Button(label='⏭')
        self.next_btn.set_name('ctrl-btn')
        self.next_btn.connect('clicked', lambda w: self.player.next())
        self.dl_btn = Gtk.Button(label='⬇')
        self.dl_btn.set_name('ctrl-btn')
        self.dl_btn.set_tooltip_text('Descargar canción actual')
        self.dl_btn.connect('clicked', lambda w: self._dl_current())

        self.vol_btn = Gtk.Button(label='🔊')
        self.vol_btn.set_name('ctrl-btn')
        self.vol_btn.connect('clicked', self.toggle_mute)

        self.vol_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol_slider.set_size_request(70, -1)
        self.vol_slider.set_draw_value(False)
        self.vol_slider.set_name('vol-slider')
        self.vol_slider.set_value(80)
        self.vol_slider.connect('value-changed', self.on_vol_change)

        ctrl_box.pack_start(self.prev_btn, False, False, 0)
        ctrl_box.pack_start(self.play_btn, False, False, 0)
        ctrl_box.pack_start(self.next_btn, False, False, 0)
        ctrl_box.pack_start(self.dl_btn, False, False, 0)
        ctrl_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        ctrl_box.pack_start(self.vol_btn, False, False, 0)
        ctrl_box.pack_start(self.vol_slider, False, False, 0)
        self.pack_start(ctrl_box, False, False, 4)

    def on_seek(self, widget, event):
        val = self.prog.get_value()
        dur = self.player.get_duration()
        if dur > 0:
            self.player.seek(val / 100.0 * dur)

    def on_vol_change(self, widget):
        val = int(self.vol_slider.get_value())
        self.player.set_volume(val / 100.0)
        self.vol_btn.set_label('🔇' if val == 0 else '🔊' if val > 50 else '🔉')

    def toggle_mute(self, widget):
        if self.vol_slider.get_value() > 0:
            self._prev_vol = self.vol_slider.get_value()
            self.vol_slider.set_value(0)
        else:
            self.vol_slider.set_value(getattr(self, '_prev_vol', 80))

    def _dl_current(self):
        vid = self.player.current_video_id
        if not vid:
            return
        title = self.title_lbl.get_text()[:60]
        import re
        safe = re.sub(r'[^\w\- ]', '', title).strip() or 'cancion'
        dest = os.path.join(DL_DIR, f'{safe}.mp3')
        win = self.get_toplevel()
        win.status_lbl.set_text(f'Descargando {safe}...')
        win.status_lbl.show()
        def dl():
            try:
                r = requests.get(f'{API_BASE}/download/{vid}.mp3', timeout=120)
                if r.status_code == 200:
                    with open(dest, 'wb') as f:
                        f.write(r.content)
                    GLib.idle_add(lambda: win.status_lbl.set_text(f'✅ {safe}.mp3 guardado'))
                else:
                    GLib.idle_add(lambda: win.status_lbl.set_text(f'Error {r.status_code}'))
            except Exception as e:
                GLib.idle_add(lambda: win.status_lbl.set_text(f'Error: {str(e)[:30]}'))
        threading.Thread(target=dl, daemon=True).start()

    def update_progress(self, pos, dur):
        if self._updating:
            return
        self._updating = True
        self.time_lbl.set_text(self._fmt(pos))
        self.dur_lbl.set_text(self._fmt(dur))
        if dur > 0:
            self.prog.set_value(pos / dur * 100.0)
        else:
            self.prog.set_value(0)
        self._updating = False

    def update_track(self, title, artist, thumb_url=None):
        self.title_lbl.set_text(title[:40])
        self.artist_lbl.set_text(artist or '')
        if thumb_url:
            def set_thumb(pix):
                self.art.set_from_pixbuf(pix)
            ThumbLoader((44, 44)).get(thumb_url, set_thumb)

    def set_playing(self, playing):
        self.play_btn.set_label('⏸' if playing else '▶')
        self.play_btn.set_name('ctrl-btn-play' if not playing else 'ctrl-btn-pause')

    @staticmethod
    def _fmt(secs):
        m, s = divmod(int(secs), 60)
        return f'{m}:{s:02d}'

class Player:
    def __init__(self, bar):
        self.bar = bar
        self.pipeline = Gst.ElementFactory.make('playbin', 'play')
        if not self.pipeline:
            print('FATAL: GStreamer playbin not available')
            sys.exit(1)
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_msg)
        self.playing = False
        self.current_video_id = None
        self.current_info = {}
        self.queue = []
        self.queue_idx = -1
        self._timer_id = None
        self._current_uri = None
        self._retry_count = 0
        self.pipeline.set_property('volume', 0.8)

    def play_url(self, video_id, info=None):
        if not video_id:
            print('WARN: empty video_id')
            return
        self.stop()
        self.current_video_id = video_id
        self.current_info = info or {}
        uri = f'{API_BASE}/stream/{video_id}'
        self._current_uri = uri
        self._retry_count = 0
        print(f'PLAY {uri}')
        self.pipeline.set_property('uri', uri)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.playing = True
        self.bar.set_playing(True)
        self.bar.update_track(
            info.get('title', 'Cargando...'),
            info.get('artist', info.get('channelTitle', '')),
            info.get('thumbnail')
        )
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(250, self._update_progress)

    def toggle(self):
        if not self.current_video_id:
            return
        if self.playing:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.playing = False
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.playing = True
        self.bar.set_playing(self.playing)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)
        self.playing = False
        self._current_uri = None
        self.bar.set_playing(False)
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def seek(self, pos_secs):
        if not self.playing:
            return
        self.pipeline.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(pos_secs * Gst.SECOND)
        )

    def set_volume(self, vol):
        self.pipeline.set_property('volume', vol)

    def get_duration(self):
        try:
            ok, dur = self.pipeline.query_duration(Gst.Format.TIME)
            if ok:
                return dur / Gst.SECOND
        except:
            pass
        return 0

    def get_position(self):
        try:
            ok, pos = self.pipeline.query_position(Gst.Format.TIME)
            if ok:
                return pos / Gst.SECOND
        except:
            pass
        return 0

    def set_queue(self, results):
        self.queue = results
        self.queue_idx = 0

    def next(self):
        if self.queue and self.queue_idx < len(self.queue) - 1:
            self.queue_idx += 1
            item = self.queue[self.queue_idx]
            self.play_url(item['video_id'], item)

    def prev(self):
        pos = self.get_position()
        if pos > 3 and self.current_video_id:
            self.seek(0)
            return
        if self.queue and self.queue_idx > 0:
            self.queue_idx -= 1
            item = self.queue[self.queue_idx]
            self.play_url(item['video_id'], item)

    def _update_progress(self):
        if self.playing:
            self.bar.update_progress(self.get_position(), self.get_duration())
        return True

    def on_msg(self, bus, msg):
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f'GST error: {err}, {dbg}')
            if self._current_uri and self._retry_count < 1:
                self._retry_count += 1
                GLib.timeout_add(800, self._retry_current)
            else:
                self.stop()
        elif t == Gst.MessageType.EOS:
            self.next()
        elif t == Gst.MessageType.BUFFERING:
            _, pct = msg.parse_buffering()
            if pct < 100:
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                if self.playing:
                    self.pipeline.set_state(Gst.State.PLAYING)
        elif t == Gst.MessageType.STATE_CHANGED:
            old, new, pend = msg.parse_state_changed()
            if new == Gst.State.PLAYING and msg.src == self.pipeline:
                self.playing = True
                self.bar.set_playing(True)

    def _retry_current(self):
        if not self._current_uri:
            return False
        print(f'RETRY {self._current_uri}')
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.set_property('uri', self._current_uri)
        self.pipeline.set_state(Gst.State.PLAYING)
        return False

class SearchResultRow(Gtk.ListBoxRow):
    def __init__(self, item, player, thumb_loader):
        super().__init__()
        self.item = item
        self.player = player
        self.set_name('search-row')
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        box = Gtk.Box(spacing=8)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        self.thumb = Gtk.Image()
        self.thumb.set_size_request(48, 48)
        self.thumb.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.thumb.set_name('result-thumb')
        box.pack_start(self.thumb, False, False, 4)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        t = item.get('title', '')
        title = Gtk.Label(label=t[:50] + ('...' if len(t) > 50 else ''))
        title.set_name('result-title')
        title.set_halign(Gtk.Align.START)
        title.set_ellipsize(Pango.EllipsizeMode.END)

        sub = f"{item.get('channelTitle', item.get('artist', ''))}  ·  {item.get('duration', '')}"
        sub_lbl = Gtk.Label(label=sub)
        sub_lbl.set_name('result-sub')
        sub_lbl.set_halign(Gtk.Align.START)
        sub_lbl.set_ellipsize(Pango.EllipsizeMode.END)

        info_box.pack_start(title, False, False, 0)
        info_box.pack_start(sub_lbl, False, False, 0)
        box.pack_start(info_box, True, True, 0)

        dl_btn = Gtk.Button(label='⬇')
        dl_btn.set_name('ctrl-btn')
        dl_btn.set_tooltip_text('Descargar MP3')
        dl_btn.connect('clicked', lambda w: self._do_download())
        box.pack_start(dl_btn, False, False, 2)

        self.add(box)

        thumb = item.get('thumbnail')
        if thumb:
            thumb_loader.get(thumb, lambda p: self.thumb.set_from_pixbuf(p))

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect('button-press-event', self.on_button_press)

    def on_button_press(self, widget, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            self.play_this()
            return True
        return False

    def play_this(self):
        self.player.play_url(self.item['video_id'], self.item)

    def _do_download(self):
        vid = self.item.get('video_id', '')
        if not vid:
            return
        title = self.item.get('title', 'cancion')[:60]
        import re
        safe = re.sub(r'[^\w\- ]', '', title).strip() or 'cancion'
        dest = os.path.join(DL_DIR, f'{safe}.mp3')
        self.get_toplevel().status_lbl.set_text(f'Descargando {safe}...')
        self.get_toplevel().status_lbl.show()
        def dl():
            try:
                r = requests.get(f'{API_BASE}/download/{vid}.mp3', timeout=120)
                if r.status_code == 200:
                    with open(dest, 'wb') as f:
                        f.write(r.content)
                    GLib.idle_add(lambda: self.get_toplevel().status_lbl.set_text(f'✅ {safe}.mp3 guardado'))
                else:
                    GLib.idle_add(lambda: self.get_toplevel().status_lbl.set_text(f'Error {r.status_code}'))
            except Exception as e:
                GLib.idle_add(lambda: self.get_toplevel().status_lbl.set_text(f'Error: {str(e)[:30]}'))
        threading.Thread(target=dl, daemon=True).start()

class SearchBar(Gtk.Box):
    def __init__(self, on_search):
        super().__init__(spacing=6)
        self.on_search = on_search
        self.set_name('search-bar')
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(8)
        self.set_margin_end(8)

        self.entry = Gtk.SearchEntry()
        self.entry.set_name('search-entry')
        self.entry.set_placeholder_text('Buscar canciones...')
        self.entry.connect('activate', self.do_search)
        self.entry.set_size_request(200, -1)
        self.pack_start(self.entry, True, True, 0)

        btn = Gtk.Button(label='🔍')
        btn.set_name('search-btn')
        btn.connect('clicked', self.do_search)
        self.pack_start(btn, False, False, 0)

    def focus_entry(self):
        self.entry.grab_focus()

    def do_search(self, widget=None):
        q = self.entry.get_text().strip()
        if q:
            self.on_search(q)

class MiniApp(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_title(APP_NAME)
        self.set_wmclass(APP_SLUG, APP_NAME)
        self.set_name('mini-window')
        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_app_paintable(True)
        self.set_accept_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect('button-press-event', self.on_window_press)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self._animating = False
        self._target_y = 0
        self._start_y = 0

        self.load_config()

        css_provider = Gtk.CssProvider()
        css = """
        #mini-window {
            background: rgba(34, 34, 38, 0.90);
            border-radius: 16px 16px 0 0;
            border: 1px solid rgba(255,255,255,0.08);
        }
        #title-bar {
            background: transparent;
            min-height: 28px;
        }
        #title-bar button {
            background: none;
            border: none;
            min-width: 13px;
            min-height: 13px;
            border-radius: 7px;
            padding: 0;
        }
        #close-btn { background: #ff5f57; }
        #close-btn:hover { background: #ff3b30; }
        #min-btn { background: #febc2e; }
        #min-btn:hover { background: #f5a623; }
        #title-label { color: rgba(255,255,255,0.7); font-size: 12px; font-weight: 600; }
        #search-bar {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 2px;
            margin: 4px 10px;
        }
        #search-entry {
            background: transparent;
            border: none;
            color: #f2f2f2;
            font-size: 14px;
        }
        #search-btn {
            background: rgba(255,255,255,0.08);
            border: none;
            border-radius: 8px;
            color: #cfcfcf;
            min-width: 32px;
            min-height: 28px;
        }
        #search-btn:hover { background: rgba(255,255,255,0.14); }
        #search-list { background: transparent; }
        #search-list row { background: transparent; }
        #result-thumb { border-radius: 6px; }
        #search-row {
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            border: none;
        }
        #search-row:hover { background: rgba(255,255,255,0.08); }
        #search-row:selected { background: rgba(255,255,255,0.12); }
        .result-title {
            color: #f2f2f2;
            font-size: 13px;
            font-weight: 600;
        }
        .result-sub {
            color: #a8a8a8;
            font-size: 11px;
        }
        #player-bar {
            background: rgba(255,255,255,0.04);
            border-top: 1px solid rgba(255,255,255,0.08);
            padding: 6px 8px;
        }
        #player-art { border-radius: 6px; }
        #player-title { color: #f2f2f2; font-size: 13px; font-weight: 600; }
        #player-artist { color: #adadad; font-size: 11px; }
        #prog-box { padding: 0 4px; }
        #prog-slider {
            background: rgba(255,255,255,0.08);
            border-radius: 4px;
            min-height: 4px;
        }
        #prog-slider trough { background: rgba(255,255,255,0.08); border-radius: 4px; min-height: 4px; }
        #prog-slider highlight { background: rgba(255,255,255,0.62); border-radius: 4px; }
        #prog-slider slider { background: rgba(255,255,255,0.8); border: none; min-width: 10px; min-height: 10px; border-radius: 5px; margin-top: -3px; }
        .time-lbl { color: #a8a8a8; font-size: 11px; font-family: monospace; }
        #ctrl-box { margin: 2px 0; }
        #ctrl-btn, #ctrl-btn-play, #ctrl-btn-pause {
            background: none;
            border: none;
            font-size: 18px;
            min-width: 32px;
            min-height: 32px;
            border-radius: 16px;
            color: #ededed;
        }
        #ctrl-btn:hover { background: rgba(255,255,255,0.08); }
        #ctrl-btn-play { background: rgba(255,255,255,0.08); color: #fafafa; }
        #ctrl-btn-pause { background: rgba(255,255,255,0.10); color: #fafafa; }
        #vol-slider { min-height: 4px; }
        #vol-slider trough { background: rgba(255,255,255,0.12); border-radius: 3px; min-height: 4px; }
        #vol-slider highlight { background: rgba(255,255,255,0.65); border-radius: 3px; }
        #vol-slider slider { background: rgba(255,255,255,0.85); border: none; min-width: 8px; min-height: 8px; border-radius: 4px; margin-top: -2px; }
        #scrolled-window { background: transparent; }
        #scrolled-window undershoot, #scrolled-window overshoot { background: none; }
        #status-lbl {
            color: #aaaaaa;
            font-size: 12px;
            padding: 20px;
        }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_name('mini-window')
        self.add(vbox)

        title_wrap = Gtk.EventBox()
        title_wrap.set_name('title-wrap')
        title_wrap.set_visible_window(False)
        title_wrap.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        title_wrap.connect('button-press-event', self.on_titlebar_press)

        title_bar = Gtk.Box(spacing=6)
        title_bar.set_name('title-bar')
        title_bar.set_margin_start(8)
        title_bar.set_margin_end(8)
        title_bar.set_margin_top(4)
        title_bar.set_hexpand(True)
        label = Gtk.Label(label='AllMusic')
        label.set_name('title-label')
        label.set_halign(Gtk.Align.START)
        label.set_margin_start(6)

        min_btn = Gtk.Button(label='')
        min_btn.set_name('min-btn')
        min_btn.set_tooltip_text('Minimizar')
        min_btn.connect('clicked', lambda w: self.iconify())
        close_btn = Gtk.Button(label='')
        close_btn.set_name('close-btn')
        close_btn.set_tooltip_text('Cerrar')
        close_btn.connect('clicked', lambda w: self.close())

        title_bar.pack_start(label, True, True, 0)
        title_bar.pack_end(close_btn, False, False, 0)
        title_bar.pack_end(min_btn, False, False, 0)
        title_wrap.add(title_bar)
        vbox.pack_start(title_wrap, False, False, 0)

        self.thumb_loader = ThumbLoader((40, 40))
        self.player_bar = PlayerBar(None)
        self.player = Player(self.player_bar)
        self.player_bar.player = self.player

        self.search_bar = SearchBar(self.do_search)
        vbox.pack_start(self.search_bar, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_name('scrolled-window')
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.list_box = Gtk.ListBox()
        self.list_box.set_name('search-list')
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.set_activate_on_single_click(False)
        self.list_box.connect('row-activated', self.on_row_activated)
        scrolled.add(self.list_box)
        vbox.pack_start(scrolled, True, True, 0)

        self.status_lbl = Gtk.Label(label='Busca tu m\xfasica favorita')
        self.status_lbl.set_name('status-lbl')
        self.status_lbl.set_xalign(0.5)
        vbox.pack_start(self.status_lbl, False, False, 0)

        vbox.pack_start(self.player_bar, False, False, 0)

        self.connect('key-press-event', self.on_key)
        self.connect('focus-out-event', self.on_focus_out)
        self.connect('window-state-event', self.on_window_state)
        self.connect('configure-event', self.on_configure)

        self._hidden = False
        self._target_y = 0
        signal.signal(signal.SIGUSR1, self.on_signal)
        self.load_geometry()

    def load_geometry(self):
        mon_x, mon_y, mon_w, mon_h = 0, 0, 1366, 768
        try:
            out = subprocess.check_output(['xrandr', '--query'], text=True)
            best = None
            for line in out.splitlines():
                if ' connected ' in line and '+' in line:
                    geom = line.split('connected', 1)[1].strip().split()[0]
                    size_part, pos_part = geom.split('+', 1)
                    w, h = [int(v) for v in size_part.split('x')]
                    x, y = [int(v) for v in pos_part.split('+')]
                    area = w * h
                    score = (1 if line.startswith('HDMI') else 0, area)
                    if best is None or score > best[0]:
                        best = (score, x, y, w, h)
            if best:
                _, mon_x, mon_y, mon_w, mon_h = best
        except Exception:
            pass

        self._mon_h = mon_h
        self._target_x = mon_x + max(0, (mon_w - WIDTH) // 2)
        self._target_y = mon_y + max(0, (mon_h - HEIGHT) // 2)
        self._restore_x = self.loaded_x or self._target_x
        self._restore_y = self.loaded_y or self._target_y
        self._anim_step = 0
        self._anim_data = None
        self.set_default_size(WIDTH, HEIGHT)

    def _animate_to(self, x1, y1, x2, y2, steps, interval, on_done):
        self._anim_step = 0
        self._anim_data = (x1, y1, x2 - x1, y2 - y1, steps, on_done)
        GLib.timeout_add(interval, self._anim_tick)

    def _anim_tick(self):
        if not self._anim_data:
            return False
        x1, y1, dx, dy, steps, on_done = self._anim_data
        self._anim_step += 1
        t = self._anim_step / steps
        if t >= 1.0:
            self.move(int(x1 + dx), int(y1 + dy))
            if on_done:
                on_done()
            self._anim_data = None
            return False
        self.move(int(x1 + dx * t), int(y1 + dy * t))
        return True

    def show_panel(self):
        if self._hidden:
            mon_h = self._mon_h
            start_y = mon_h + 50
            tx = self._restore_x
            ty = self._restore_y
            self.show_all()
            self.deiconify()
            self.present()
            self.move(tx, start_y)
            self._animate_to(tx, start_y, tx, ty, 12, 20, None)
        else:
            self.load_geometry()
            if self.loaded_x and self.loaded_y:
                self.move(self.loaded_x, self.loaded_y)
        self._hidden = False
        self._shown_at = time.time()
        GLib.timeout_add(150, self.search_bar.focus_entry)

    def on_titlebar_press(self, widget, event):
        if event.button == 1 and event.x > 20:
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def on_window_press(self, widget, event):
        if event.button == 1 and event.y < 12:
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def hide_panel(self):
        self._hidden = True
        cur_x, cur_y = self.get_position()
        self._restore_x, self._restore_y = cur_x, cur_y
        target_y = self._mon_h + 50
        self._animate_to(cur_x, cur_y, cur_x, target_y, 15, 20, self._really_hide)

    def _really_hide(self):
        self.hide()

    def on_row_activated(self, listbox, row):
        row.play_this()

    def do_search(self, query):
        self.status_lbl.set_text('Buscando...')
        self.status_lbl.show()
        for row in self.list_box.get_children():
            self.list_box.remove(row)

        def search_thread():
            try:
                r = requests.get(f'{API_BASE}/search', params={'q': query, 'limit': 25}, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    results = data.get('results', [])
                    normalized = []
                    for item in results:
                        vid = item.get('videoId') or item.get('video_id') or item.get('id') or ''
                        normalized.append({
                            'video_id': vid,
                            'title': item.get('title', ''),
                            'channelTitle': item.get('channelTitle', item.get('artist', '')),
                            'thumbnail': item.get('thumbnail', item.get('thumbnails', [{}])[0].get('url', '') if isinstance(item.get('thumbnails'), list) else ''),
                            'duration': item.get('duration', ''),
                        })
                    GLib.idle_add(self.display_results, normalized)
                else:
                    GLib.idle_add(lambda: self.status_lbl.set_text(f'Error {r.status_code}'))
            except Exception as e:
                GLib.idle_add(lambda: self.status_lbl.set_text(f'Error: {str(e)[:40]}'))

        threading.Thread(target=search_thread, daemon=True).start()

    def display_results(self, results):
        self.status_lbl.hide()
        if not results:
            self.status_lbl.set_text('Sin resultados')
            self.status_lbl.show()
            return
        for item in results:
            row = SearchResultRow(item, self.player, self.thumb_loader)
            self.list_box.add(row)
        self.list_box.show_all()
        self.player.set_queue(results)

    def on_key(self, widget, event):
        key = event.get_keyval()[1]
        focus = self.get_focus()
        if key == Gdk.KEY_Escape:
            self.hide_panel()
        elif key == Gdk.KEY_F3:
            self.hide_panel()
        elif key == Gdk.KEY_space and not isinstance(focus, Gtk.Entry):
            self.player.toggle()
            return True
        elif key == Gdk.KEY_Left:
            self.player.seek(max(0, self.player.get_position() - 5))
        elif key == Gdk.KEY_Right:
            self.player.seek(self.player.get_position() + 5)
        return False

    def on_focus_out(self, widget, event):
        return False

    def do_auto_hide(self):
        return False

    def on_window_state(self, widget, event):
        if event.changed_mask & Gdk.WindowState.WITHDRAWN:
            pass
        return False

    def on_signal(self, signum, frame):
        GLib.idle_add(self.toggle_visible)

    def toggle_visible(self):
        if self._hidden:
            self.show_panel()
        else:
            self.hide_panel()

    def on_configure(self, widget, event):
        if not self._hidden and not self._anim_data:
            x, y = self.get_position()
            self._restore_x, self._restore_y = x, y
        return False

    def save_window_state(self):
        try:
            x, y = self.get_position()
            os.makedirs(CFG_DIR, exist_ok=True)
            with open(CFG_FILE, 'w') as f:
                json.dump({'x': x, 'y': y, 'api_base': API_BASE, 'dl_dir': DL_DIR}, f)
        except:
            pass

    def load_config(self):
        global API_BASE, DL_DIR
        self.loaded_x = None
        self.loaded_y = None
        try:
            if os.path.exists(CFG_FILE):
                with open(CFG_FILE) as f:
                    d = json.load(f)
                self.loaded_x = d.get('x')
                self.loaded_y = d.get('y')
                if 'api_base' in d:
                    API_BASE = d['api_base']
                if 'dl_dir' in d:
                    DL_DIR = d['dl_dir']
        except:
            pass

    def do_delete_event(self, *args):
        self.save_window_state()
        self.player.stop()
        return False

    def do_destroy(self):
        self.save_window_state()
        self.player.stop()
        Gtk.main_quit()

if __name__ == '__main__':
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(os.path.join(CFG_DIR, 'pid'), 'w') as f:
        f.write(str(os.getpid()))
    app = MiniApp()
    if '--hidden' in sys.argv:
        app.hide_panel()
    else:
        app.show_panel()
    Gtk.main()
