#!/usr/bin/env python3
"""AllMusic 2.1 - Native desktop mini app with an evolved radio experience."""
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
import random

APP_NAME = 'AllMusic 2.1'
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
    except Exception:
        pass
    API_BASE = os.environ.get('ALLMUSIC_API_BASE') or cfg.get(
        'api_base', 'https://edgemarketing.art/allmusic'
    )
    DL_DIR = cfg.get('dl_dir', os.path.expanduser('~/Descargas'))


_load_env()

WIDTH = 460
HEIGHT = 700
Gst.init(None)


class ThumbLoader:
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    }

    def __init__(self, size=(48, 48)):
        self.size = size
        self.cache = {}

    def get(self, url, callback):
        if not url:
            return
        if url in self.cache:
            pix = self.cache[url]
            if pix:
                GLib.idle_add(callback, pix)
            return

        def load():
            pix = None
            attempts = [
                url,
                url.replace('hqdefault', 'mqdefault'),
                url.replace('hqdefault', 'default'),
            ]
            for attempt_url in attempts:
                try:
                    r = requests.get(attempt_url, headers=self.HEADERS, timeout=8)
                    if r.status_code == 200 and len(r.content) > 100:
                        tmp = '/tmp/am_thumb_' + str(hash(attempt_url)) + '.jpg'
                        with open(tmp, 'wb') as f:
                            f.write(r.content)
                        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                            tmp, self.size[0], self.size[1], True
                        )
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
                        break
                except Exception:
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
        self._prev_vol = 80
        self.set_name('player-bar')

        meta_row = Gtk.Box(spacing=10)
        meta_row.set_name('player-meta-row')

        art_frame = Gtk.EventBox()
        art_frame.set_name('player-art-frame')
        self.art = Gtk.Image()
        self.art.set_size_request(56, 56)
        self.art.set_name('player-art')
        self.art.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        art_frame.add(self.art)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_head = Gtk.Box(spacing=6)
        self.mode_badge = Gtk.Label(label='MÚSICA')
        self.mode_badge.set_name('mode-badge')
        self.live_dot = Gtk.Label(label='')
        self.live_dot.set_name('live-dot')
        info_head.pack_start(self.mode_badge, False, False, 0)
        info_head.pack_start(self.live_dot, False, False, 0)

        self.title_lbl = Gtk.Label(label=APP_NAME)
        self.title_lbl.set_name('player-title')
        self.title_lbl.set_halign(Gtk.Align.START)
        self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_lbl = Gtk.Label(label='Listo para reproducir')
        self.artist_lbl.set_name('player-artist')
        self.artist_lbl.set_halign(Gtk.Align.START)
        self.artist_lbl.set_ellipsize(Pango.EllipsizeMode.END)

        info_box.pack_start(info_head, False, False, 0)
        info_box.pack_start(self.title_lbl, False, False, 0)
        info_box.pack_start(self.artist_lbl, False, False, 0)

        meta_row.pack_start(art_frame, False, False, 0)
        meta_row.pack_start(info_box, True, True, 0)
        self.pack_start(meta_row, False, False, 0)

        self.prog_box = Gtk.Box(spacing=7)
        self.prog_box.set_name('prog-box')
        self.time_lbl = Gtk.Label(label='0:00')
        self.time_lbl.set_name('time-lbl')
        self.prog = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.5)
        self.prog.set_size_request(-1, 10)
        self.prog.set_slider_size_fixed(False)
        self.prog.set_draw_value(False)
        self.prog.set_name('prog-slider')
        self.prog.connect('button-release-event', self.on_seek)
        self.dur_lbl = Gtk.Label(label='0:00')
        self.dur_lbl.set_name('time-lbl')
        self.prog_box.pack_start(self.time_lbl, False, False, 0)
        self.prog_box.pack_start(self.prog, True, True, 0)
        self.prog_box.pack_start(self.dur_lbl, False, False, 0)
        self.pack_start(self.prog_box, False, False, 6)

        self.radio_line = Gtk.Box(spacing=8)
        self.radio_line.set_name('radio-line')
        radio_icon = Gtk.Label(label='◉')
        radio_icon.set_name('radio-pulse')
        self.radio_line_lbl = Gtk.Label(label='Radio continua activa')
        self.radio_line_lbl.set_name('radio-line-label')
        self.radio_line_lbl.set_halign(Gtk.Align.START)
        self.radio_line.pack_start(radio_icon, False, False, 0)
        self.radio_line.pack_start(self.radio_line_lbl, True, True, 0)
        self.radio_line.set_no_show_all(True)
        self.radio_line.hide()
        self.pack_start(self.radio_line, False, False, 4)

        ctrl_box = Gtk.Box(spacing=8)
        ctrl_box.set_name('ctrl-box')
        ctrl_box.set_halign(Gtk.Align.CENTER)

        self.prev_btn = Gtk.Button(label='⏮')
        self.prev_btn.set_name('ctrl-btn')
        self.prev_btn.set_tooltip_text('Anterior')
        self.prev_btn.connect('clicked', lambda w: self.player.prev())

        self.play_btn = Gtk.Button(label='▶')
        self.play_btn.set_name('ctrl-btn-play')
        self.play_btn.set_tooltip_text('Reproducir / Pausar')
        self.play_btn.connect('clicked', lambda w: self.player.toggle())

        self.next_btn = Gtk.Button(label='⏭')
        self.next_btn.set_name('ctrl-btn')
        self.next_btn.set_tooltip_text('Siguiente')
        self.next_btn.connect('clicked', lambda w: self.player.next())

        self.dl_btn = Gtk.Button(label='⬇')
        self.dl_btn.set_name('ctrl-btn')
        self.dl_btn.set_tooltip_text('Descargar canción actual')
        self.dl_btn.connect('clicked', lambda w: self._dl_current())

        self.vol_btn = Gtk.Button(label='🔊')
        self.vol_btn.set_name('ctrl-btn')
        self.vol_btn.connect('clicked', self.toggle_mute)

        self.vol_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol_slider.set_size_request(72, -1)
        self.vol_slider.set_draw_value(False)
        self.vol_slider.set_name('vol-slider')
        self.vol_slider.set_value(80)
        self.vol_slider.connect('value-changed', self.on_vol_change)

        ctrl_box.pack_start(self.prev_btn, False, False, 0)
        ctrl_box.pack_start(self.play_btn, False, False, 0)
        ctrl_box.pack_start(self.next_btn, False, False, 0)
        ctrl_box.pack_start(self.dl_btn, False, False, 0)
        ctrl_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 5)
        ctrl_box.pack_start(self.vol_btn, False, False, 0)
        ctrl_box.pack_start(self.vol_slider, False, False, 0)
        self.pack_start(ctrl_box, False, False, 4)

    def on_seek(self, widget, event):
        if self.player.radio_mode:
            return
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
            self.vol_slider.set_value(self._prev_vol or 80)

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
                    os.makedirs(DL_DIR, exist_ok=True)
                    with open(dest, 'wb') as f:
                        f.write(r.content)
                    GLib.idle_add(lambda: win.status_lbl.set_text(f'✓ {safe}.mp3 guardado'))
                else:
                    GLib.idle_add(lambda: win.status_lbl.set_text(f'Error {r.status_code}'))
            except Exception as e:
                GLib.idle_add(lambda: win.status_lbl.set_text(f'Error: {str(e)[:30]}'))

        threading.Thread(target=dl, daemon=True).start()

    def update_progress(self, pos, dur):
        if self._updating or self.player.radio_mode:
            return
        self._updating = True
        self.time_lbl.set_text(self._fmt(pos))
        self.dur_lbl.set_text(self._fmt(dur))
        self.prog.set_value(pos / dur * 100.0 if dur > 0 else 0)
        self._updating = False

    def update_track(self, title, artist, thumb_url=None):
        self.title_lbl.set_text((title or 'Sin título')[:52])
        self.artist_lbl.set_text((artist or 'AllMusic')[:52])
        if thumb_url:
            ThumbLoader((52, 52)).get(thumb_url, lambda pix: self.art.set_from_pixbuf(pix))

    def set_mode(self, radio=False, seed=''):
        self.mode_badge.set_text('RADIO' if radio else 'MÚSICA')
        self.live_dot.set_text('● EN VIVO' if radio else '')
        self.dl_btn.set_sensitive(True)
        if radio:
            self.radio_line_lbl.set_text(f'Estación continua · {seed}' if seed else 'Estación continua activa')
            self.radio_line.show_all()
            self.prog_box.hide()
        else:
            self.radio_line.hide()
            self.prog_box.show_all()

    def set_playing(self, playing):
        self.play_btn.set_label('⏸' if playing else '▶')
        self.play_btn.set_name('ctrl-btn-pause' if playing else 'ctrl-btn-play')

    @staticmethod
    def _fmt(secs):
        m, s = divmod(max(0, int(secs)), 60)
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
        self.radio_mode = False
        self.radio_seed = ''
        self._timer_id = None
        self._current_uri = None
        self._retry_count = 0
        self.pipeline.set_property('volume', 0.8)

    def play_url(self, video_id, info=None, preserve_radio=False):
        if not video_id:
            print('WARN: empty video_id')
            return
        if not preserve_radio:
            self.radio_mode = False
            self.radio_seed = ''
            self.bar.set_mode(False)
        self.stop(preserve_mode=True)
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
            self.current_info.get('title', 'Cargando...'),
            self.current_info.get('artist', self.current_info.get('channelTitle', '')),
            self.current_info.get('thumbnail'),
        )
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(250, self._update_progress)

    def start_radio(self, results, seed):
        if not results:
            return
        self.radio_mode = True
        self.radio_seed = seed
        self.queue = list(results)
        random.shuffle(self.queue)
        self.queue_idx = 0
        self.bar.set_mode(True, seed)
        self.play_url(self.queue[self.queue_idx]['video_id'], self.queue[self.queue_idx], preserve_radio=True)

    def stop_radio(self):
        self.radio_mode = False
        self.radio_seed = ''
        self.bar.set_mode(False)

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

    def stop(self, preserve_mode=False):
        self.pipeline.set_state(Gst.State.NULL)
        self.playing = False
        self._current_uri = None
        self.bar.set_playing(False)
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        if not preserve_mode:
            self.stop_radio()

    def seek(self, pos_secs):
        if not self.playing or self.radio_mode:
            return
        self.pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(pos_secs * Gst.SECOND),
        )

    def set_volume(self, vol):
        self.pipeline.set_property('volume', vol)

    def get_duration(self):
        try:
            ok, dur = self.pipeline.query_duration(Gst.Format.TIME)
            if ok:
                return dur / Gst.SECOND
        except Exception:
            pass
        return 0

    def get_position(self):
        try:
            ok, pos = self.pipeline.query_position(Gst.Format.TIME)
            if ok:
                return pos / Gst.SECOND
        except Exception:
            pass
        return 0

    def set_queue(self, results):
        self.queue = results
        self.queue_idx = 0 if results else -1
        self.radio_mode = False
        self.radio_seed = ''
        self.bar.set_mode(False)

    def next(self):
        if not self.queue:
            return
        if self.radio_mode:
            self.queue_idx = (self.queue_idx + 1) % len(self.queue)
            item = self.queue[self.queue_idx]
            self.play_url(item['video_id'], item, preserve_radio=True)
            return
        if self.queue_idx < len(self.queue) - 1:
            self.queue_idx += 1
            item = self.queue[self.queue_idx]
            self.play_url(item['video_id'], item)

    def prev(self):
        if not self.queue:
            return
        if not self.radio_mode:
            pos = self.get_position()
            if pos > 3 and self.current_video_id:
                self.seek(0)
                return
        if self.radio_mode:
            self.queue_idx = (self.queue_idx - 1) % len(self.queue)
            item = self.queue[self.queue_idx]
            self.play_url(item['video_id'], item, preserve_radio=True)
            return
        if self.queue_idx > 0:
            self.queue_idx -= 1
            item = self.queue[self.queue_idx]
            self.play_url(item['video_id'], item)

    def _update_progress(self):
        if self.playing and not self.radio_mode:
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
                self.stop(preserve_mode=self.radio_mode)
                if self.radio_mode:
                    GLib.timeout_add(400, self._advance_after_error)
        elif t == Gst.MessageType.EOS:
            self.next()
        elif t == Gst.MessageType.BUFFERING:
            _, pct = msg.parse_buffering()
            if pct < 100:
                self.pipeline.set_state(Gst.State.PAUSED)
            elif self.playing:
                self.pipeline.set_state(Gst.State.PLAYING)
        elif t == Gst.MessageType.STATE_CHANGED:
            old, new, pend = msg.parse_state_changed()
            if new == Gst.State.PLAYING and msg.src == self.pipeline:
                self.playing = True
                self.bar.set_playing(True)

    def _advance_after_error(self):
        if self.radio_mode:
            self.next()
        return False

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
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(3)
        self.set_margin_bottom(3)

        box = Gtk.Box(spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        thumb_frame = Gtk.EventBox()
        thumb_frame.set_name('result-thumb-frame')
        self.thumb = Gtk.Image()
        self.thumb.set_size_request(52, 52)
        self.thumb.set_from_icon_name('audio-x-generic', Gtk.IconSize.DIALOG)
        self.thumb.set_name('result-thumb')
        thumb_frame.add(self.thumb)
        box.pack_start(thumb_frame, False, False, 4)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t = item.get('title', '')
        title = Gtk.Label(label=t[:56] + ('…' if len(t) > 56 else ''))
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

        play_btn = Gtk.Button(label='▶')
        play_btn.set_name('row-play-btn')
        play_btn.set_tooltip_text('Reproducir')
        play_btn.connect('clicked', lambda w: self.play_this())
        box.pack_start(play_btn, False, False, 0)

        dl_btn = Gtk.Button(label='↓')
        dl_btn.set_name('row-action-btn')
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
        win = self.get_toplevel()
        win.status_lbl.set_text(f'Descargando {safe}...')
        win.status_lbl.show()

        def dl():
            try:
                r = requests.get(f'{API_BASE}/download/{vid}.mp3', timeout=120)
                if r.status_code == 200:
                    os.makedirs(DL_DIR, exist_ok=True)
                    with open(dest, 'wb') as f:
                        f.write(r.content)
                    GLib.idle_add(lambda: win.status_lbl.set_text(f'✓ {safe}.mp3 guardado'))
                else:
                    GLib.idle_add(lambda: win.status_lbl.set_text(f'Error {r.status_code}'))
            except Exception as e:
                GLib.idle_add(lambda: win.status_lbl.set_text(f'Error: {str(e)[:30]}'))

        threading.Thread(target=dl, daemon=True).start()


class SearchBar(Gtk.Box):
    def __init__(self, on_search):
        super().__init__(spacing=6)
        self.on_search = on_search
        self.set_name('search-bar')
        self.set_margin_top(7)
        self.set_margin_bottom(8)
        self.set_margin_start(10)
        self.set_margin_end(10)

        self.entry = Gtk.SearchEntry()
        self.entry.set_name('search-entry')
        self.entry.set_placeholder_text('Artista, canción, álbum…')
        self.entry.connect('activate', self.do_search)
        self.entry.set_size_request(220, -1)
        self.pack_start(self.entry, True, True, 0)

        btn = Gtk.Button(label='BUSCAR')
        btn.set_name('search-btn')
        btn.connect('clicked', self.do_search)
        self.pack_start(btn, False, False, 0)

    def focus_entry(self):
        self.entry.grab_focus()
        return False

    def do_search(self, widget=None):
        q = self.entry.get_text().strip()
        if q:
            self.on_search(q)


class ModeNav(Gtk.Box):
    def __init__(self, on_mode):
        super().__init__(spacing=6)
        self.on_mode = on_mode
        self.set_name('mode-nav')
        self.set_halign(Gtk.Align.FILL)
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_bottom(2)

        self.music_btn = Gtk.Button(label='♫  Explorar')
        self.music_btn.set_name('mode-btn-active')
        self.music_btn.connect('clicked', lambda w: self.activate('music'))
        self.radio_btn = Gtk.Button(label='◉  Radio')
        self.radio_btn.set_name('mode-btn')
        self.radio_btn.connect('clicked', lambda w: self.activate('radio'))
        self.pack_start(self.music_btn, True, True, 0)
        self.pack_start(self.radio_btn, True, True, 0)

    def activate(self, mode):
        self.music_btn.set_name('mode-btn-active' if mode == 'music' else 'mode-btn')
        self.radio_btn.set_name('mode-btn-active' if mode == 'radio' else 'mode-btn')
        self.on_mode(mode)


class RadioView(Gtk.Box):
    PRESETS = [
        ('Rock', 'rock classics alternative'),
        ('Indie', 'indie alternative'),
        ('Latino', 'latin pop urbano'),
        ('Electrónica', 'electronic dance chill'),
        ('90s', '90s hits'),
        ('Jazz', 'jazz soul chill'),
    ]

    def __init__(self, on_start_radio):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.on_start_radio = on_start_radio
        self.set_name('radio-view')
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(8)
        self.set_margin_bottom(10)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hero.set_name('radio-hero')
        hero.set_margin_top(8)
        hero.set_margin_bottom(4)
        hero.set_margin_start(8)
        hero.set_margin_end(8)

        live_row = Gtk.Box(spacing=7)
        live_row.set_halign(Gtk.Align.START)
        dot = Gtk.Label(label='●')
        dot.set_name('radio-live-dot')
        live = Gtk.Label(label='ALLMUSIC RADIO')
        live.set_name('radio-kicker')
        live_row.pack_start(dot, False, False, 0)
        live_row.pack_start(live, False, False, 0)

        title = Gtk.Label(label='Tu estación. Sin cortes.')
        title.set_name('radio-title')
        title.set_halign(Gtk.Align.START)
        subtitle = Gtk.Label(label='Elige un mood, género o artista. AllMusic construye una cola continua y la mantiene viva.')
        subtitle.set_name('radio-subtitle')
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_line_wrap(True)
        subtitle.set_max_width_chars(44)

        hero.pack_start(live_row, False, False, 0)
        hero.pack_start(title, False, False, 0)
        hero.pack_start(subtitle, False, False, 0)
        self.pack_start(hero, False, False, 0)

        equalizer = Gtk.Box(spacing=4)
        equalizer.set_name('radio-equalizer')
        equalizer.set_halign(Gtk.Align.CENTER)
        for bar in ['▂', '▅', '▇', '▄', '▆', '▃', '▇', '▅', '▂', '▆', '▄', '▇']:
            lbl = Gtk.Label(label=bar)
            lbl.set_name('eq-bar')
            equalizer.pack_start(lbl, False, False, 0)
        self.pack_start(equalizer, False, False, 4)

        seed_wrap = Gtk.Box(spacing=6)
        seed_wrap.set_name('radio-seed-wrap')
        self.seed_entry = Gtk.Entry()
        self.seed_entry.set_name('radio-seed-entry')
        self.seed_entry.set_placeholder_text('Ej: Daft Punk, salsa, synthwave, Cerati…')
        self.seed_entry.connect('activate', self._start_custom)
        seed_wrap.pack_start(self.seed_entry, True, True, 0)

        start_btn = Gtk.Button(label='INICIAR RADIO')
        start_btn.set_name('radio-start-btn')
        start_btn.connect('clicked', self._start_custom)
        seed_wrap.pack_start(start_btn, False, False, 0)
        self.pack_start(seed_wrap, False, False, 2)

        presets_title = Gtk.Label(label='ESTACIONES RÁPIDAS')
        presets_title.set_name('section-kicker')
        presets_title.set_halign(Gtk.Align.START)
        self.pack_start(presets_title, False, False, 2)

        preset_grid = Gtk.Grid()
        preset_grid.set_row_spacing(6)
        preset_grid.set_column_spacing(6)
        for idx, (label, query) in enumerate(self.PRESETS):
            btn = Gtk.Button(label=label)
            btn.set_name('preset-btn')
            btn.connect('clicked', self._preset_clicked, query, label)
            preset_grid.attach(btn, idx % 3, idx // 3, 1, 1)
        self.pack_start(preset_grid, False, False, 0)

        self.station_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.station_card.set_name('station-card')
        self.station_card.set_margin_top(8)
        self.station_card.set_no_show_all(True)
        self.station_card.hide()

        station_top = Gtk.Box(spacing=8)
        self.station_live = Gtk.Label(label='● EN VIVO')
        self.station_live.set_name('station-live')
        self.station_name = Gtk.Label(label='')
        self.station_name.set_name('station-name')
        self.station_name.set_halign(Gtk.Align.START)
        station_top.pack_start(self.station_live, False, False, 0)
        station_top.pack_start(self.station_name, True, True, 0)
        self.station_desc = Gtk.Label(label='')
        self.station_desc.set_name('station-desc')
        self.station_desc.set_halign(Gtk.Align.START)
        self.station_desc.set_line_wrap(True)
        self.station_card.pack_start(station_top, False, False, 0)
        self.station_card.pack_start(self.station_desc, False, False, 0)
        self.pack_start(self.station_card, False, False, 0)

    def _start_custom(self, widget=None):
        seed = self.seed_entry.get_text().strip()
        if seed:
            self.on_start_radio(seed, seed)

    def _preset_clicked(self, widget, query, label):
        self.seed_entry.set_text(label)
        self.on_start_radio(query, label)

    def show_station(self, label, count):
        self.station_name.set_text(label.upper())
        self.station_desc.set_text(f'{count} tracks mezclados en una estación continua. Usa ⏭ para saltar sin salir de Radio.')
        self.station_card.show_all()


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
        self._current_mode = 'music'
        self._radio_request_id = 0

        self.load_config()
        self._load_css(screen)

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
        title_bar.set_margin_start(10)
        title_bar.set_margin_end(10)
        title_bar.set_margin_top(7)
        title_bar.set_margin_bottom(3)
        title_bar.set_hexpand(True)

        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        brand_label = Gtk.Label(label='ALLMUSIC')
        brand_label.set_name('title-label')
        brand_label.set_halign(Gtk.Align.START)
        brand_sub = Gtk.Label(label='YOUR MUSIC, ONE PLACE')
        brand_sub.set_name('title-sub')
        brand_sub.set_halign(Gtk.Align.START)
        brand_box.pack_start(brand_label, False, False, 0)
        brand_box.pack_start(brand_sub, False, False, 0)

        min_btn = Gtk.Button(label='')
        min_btn.set_name('min-btn')
        min_btn.set_tooltip_text('Minimizar')
        min_btn.connect('clicked', lambda w: self.iconify())
        close_btn = Gtk.Button(label='')
        close_btn.set_name('close-btn')
        close_btn.set_tooltip_text('Cerrar')
        close_btn.connect('clicked', lambda w: self.close())

        title_bar.pack_start(brand_box, True, True, 0)
        title_bar.pack_end(close_btn, False, False, 0)
        title_bar.pack_end(min_btn, False, False, 0)
        title_wrap.add(title_bar)
        vbox.pack_start(title_wrap, False, False, 0)

        self.mode_nav = ModeNav(self.switch_mode)
        vbox.pack_start(self.mode_nav, False, False, 0)

        self.thumb_loader = ThumbLoader((52, 52))
        self.player_bar = PlayerBar(None)
        self.player = Player(self.player_bar)
        self.player_bar.player = self.player

        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_transition_duration(180)
        self.content_stack.set_vexpand(True)

        music_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.search_bar = SearchBar(self.do_search)
        music_page.pack_start(self.search_bar, False, False, 0)

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
        music_page.pack_start(scrolled, True, True, 0)

        self.status_lbl = Gtk.Label(label='Busca tu música favorita')
        self.status_lbl.set_name('status-lbl')
        self.status_lbl.set_xalign(0.5)
        music_page.pack_start(self.status_lbl, False, False, 0)

        self.radio_view = RadioView(self.start_radio)
        self.content_stack.add_named(music_page, 'music')
        self.content_stack.add_named(self.radio_view, 'radio')
        vbox.pack_start(self.content_stack, True, True, 0)
        vbox.pack_start(self.player_bar, False, False, 0)

        self.connect('key-press-event', self.on_key)
        self.connect('focus-out-event', self.on_focus_out)
        self.connect('window-state-event', self.on_window_state)
        self.connect('configure-event', self.on_configure)

        self._hidden = False
        self._target_y = 0
        signal.signal(signal.SIGUSR1, self.on_signal)
        self.load_geometry()

    def _load_css(self, screen):
        css_provider = Gtk.CssProvider()
        css = """
        #mini-window {
            background: rgba(13, 14, 18, 0.965);
            border-radius: 20px 20px 0 0;
            border: 1px solid rgba(255,255,255,0.08);
        }
        #title-bar { background: transparent; min-height: 42px; }
        #title-bar button {
            background: none; border: none; min-width: 13px; min-height: 13px;
            border-radius: 7px; padding: 0;
        }
        #close-btn { background: #ff5f57; }
        #close-btn:hover { background: #ff3b30; }
        #min-btn { background: #febc2e; }
        #min-btn:hover { background: #f5a623; }
        #title-label { color: #ffffff; font-size: 13px; font-weight: 800; letter-spacing: 1px; }
        #title-sub { color: rgba(255,255,255,0.34); font-size: 8px; font-weight: 700; letter-spacing: 1px; }

        #mode-nav { background: rgba(255,255,255,0.025); border-radius: 11px; padding: 3px; }
        #mode-btn, #mode-btn-active {
            border: none; border-radius: 9px; min-height: 32px; font-size: 12px; font-weight: 700;
        }
        #mode-btn { background: transparent; color: rgba(255,255,255,0.50); }
        #mode-btn:hover { background: rgba(255,255,255,0.05); color: #fff; }
        #mode-btn-active { background: rgba(255,255,255,0.10); color: #fff; }

        #search-bar {
            background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.055);
            border-radius: 12px; padding: 3px; margin: 3px 0;
        }
        #search-entry { background: transparent; border: none; color: #f7f7f8; font-size: 14px; min-height: 31px; }
        #search-entry selection { background: rgba(130,88,255,0.55); }
        #search-btn {
            background: linear-gradient(90deg, #7657ff, #a855f7); border: none; border-radius: 9px;
            color: #fff; min-width: 70px; min-height: 30px; font-size: 9px; font-weight: 800;
        }
        #search-btn:hover { background: linear-gradient(90deg, #8568ff, #b56bfa); }

        #search-list, #search-list row { background: transparent; }
        #search-row { background: rgba(255,255,255,0.025); border-radius: 11px; border: 1px solid rgba(255,255,255,0.025); }
        #search-row:hover { background: rgba(255,255,255,0.060); border-color: rgba(255,255,255,0.065); }
        #search-row:selected { background: rgba(118,87,255,0.17); border-color: rgba(139,105,255,0.25); }
        #result-thumb-frame { background: #171820; border-radius: 9px; padding: 0; }
        #result-title { color: #f5f5f7; font-size: 13px; font-weight: 700; }
        #result-sub { color: #8f9099; font-size: 10px; }
        #row-play-btn, #row-action-btn { border: none; border-radius: 16px; min-width: 30px; min-height: 30px; }
        #row-play-btn { background: rgba(118,87,255,0.18); color: #c9bcff; }
        #row-play-btn:hover { background: rgba(118,87,255,0.34); color: #fff; }
        #row-action-btn { background: transparent; color: #a4a5ae; }
        #row-action-btn:hover { background: rgba(255,255,255,0.07); color: #fff; }

        #radio-view { background: transparent; }
        #radio-hero {
            background: linear-gradient(135deg, rgba(76,29,149,0.36), rgba(10,10,16,0.28));
            border: 1px solid rgba(167,139,250,0.18); border-radius: 16px; padding: 14px;
        }
        #radio-live-dot { color: #ff4d6d; font-size: 10px; }
        #radio-kicker { color: #c4b5fd; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
        #radio-title { color: #fff; font-size: 24px; font-weight: 800; }
        #radio-subtitle { color: rgba(255,255,255,0.60); font-size: 11px; }
        #radio-equalizer { min-height: 26px; }
        #eq-bar { color: #9b87ff; font-size: 20px; font-weight: 900; }
        #radio-seed-wrap { background: rgba(255,255,255,0.045); border-radius: 12px; padding: 4px; }
        #radio-seed-entry { background: transparent; border: none; color: #fff; min-height: 31px; font-size: 12px; }
        #radio-start-btn {
            background: linear-gradient(90deg, #7c3aed, #ec4899); border: none; border-radius: 9px;
            min-height: 31px; color: #fff; font-size: 9px; font-weight: 800;
        }
        #section-kicker { color: #777985; font-size: 9px; font-weight: 800; letter-spacing: 1px; margin-top: 5px; }
        #preset-btn {
            background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.055);
            border-radius: 10px; color: #d7d7dc; min-height: 34px; font-size: 11px; font-weight: 700;
        }
        #preset-btn:hover { background: rgba(124,58,237,0.17); border-color: rgba(167,139,250,0.25); color: #fff; }
        #station-card {
            background: rgba(255,77,109,0.06); border: 1px solid rgba(255,77,109,0.14);
            border-radius: 12px; padding: 10px 12px;
        }
        #station-live { color: #ff6680; font-size: 9px; font-weight: 900; }
        #station-name { color: #fff; font-size: 12px; font-weight: 800; }
        #station-desc { color: #a7a7b0; font-size: 10px; }

        #player-bar {
            background: rgba(18,19,25,0.985); border-top: 1px solid rgba(255,255,255,0.07);
            padding: 10px 12px 9px 12px;
        }
        #player-art-frame { background: #20212a; border-radius: 11px; padding: 0; }
        #mode-badge {
            background: rgba(118,87,255,0.14); color: #ad9cff; border-radius: 5px;
            padding: 2px 6px; font-size: 8px; font-weight: 900;
        }
        #live-dot { color: #ff5370; font-size: 8px; font-weight: 900; }
        #player-title { color: #f8f8fa; font-size: 13px; font-weight: 800; }
        #player-artist { color: #8c8e99; font-size: 10px; }
        #prog-box { padding: 0 2px; }
        #prog-slider trough { background: rgba(255,255,255,0.08); border-radius: 4px; min-height: 4px; }
        #prog-slider highlight { background: linear-gradient(90deg, #7657ff, #ec4899); border-radius: 4px; }
        #prog-slider slider { background: #fff; border: none; min-width: 10px; min-height: 10px; border-radius: 5px; margin-top: -3px; }
        #time-lbl { color: #6f717c; font-size: 9px; font-family: monospace; }
        #radio-line { background: rgba(255,77,109,0.045); border-radius: 8px; padding: 4px 8px; }
        #radio-pulse { color: #ff5370; font-size: 9px; }
        #radio-line-label { color: #b9bac2; font-size: 9px; font-weight: 700; }
        #ctrl-box { margin: 1px 0; }
        #ctrl-btn, #ctrl-btn-play, #ctrl-btn-pause {
            border: none; font-size: 16px; min-width: 34px; min-height: 34px; border-radius: 17px; color: #ededf0;
        }
        #ctrl-btn { background: transparent; }
        #ctrl-btn:hover { background: rgba(255,255,255,0.07); }
        #ctrl-btn-play { background: linear-gradient(135deg, #7657ff, #9c6bff); color: #fff; }
        #ctrl-btn-pause { background: linear-gradient(135deg, #8b5cf6, #ec4899); color: #fff; }
        #vol-slider trough { background: rgba(255,255,255,0.10); border-radius: 3px; min-height: 4px; }
        #vol-slider highlight { background: #9b87ff; border-radius: 3px; }
        #vol-slider slider { background: #ddd; border: none; min-width: 8px; min-height: 8px; border-radius: 4px; margin-top: -2px; }

        #scrolled-window { background: transparent; }
        #scrolled-window undershoot, #scrolled-window overshoot { background: none; }
        #status-lbl { color: #737580; font-size: 11px; padding: 18px; }
        scrollbar slider { background: rgba(255,255,255,0.14); border-radius: 6px; min-width: 5px; }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def switch_mode(self, mode):
        self._current_mode = mode
        self.content_stack.set_visible_child_name(mode)
        if mode == 'music':
            GLib.timeout_add(100, self.search_bar.focus_entry)
        else:
            self.radio_view.seed_entry.grab_focus()

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
        if self._current_mode == 'music':
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

    def _normalize_results(self, data):
        results = data.get('results', []) if isinstance(data, dict) else []
        normalized = []
        for item in results:
            vid = item.get('videoId') or item.get('video_id') or item.get('id') or ''
            if not vid:
                continue
            thumbs = item.get('thumbnails')
            thumb = item.get('thumbnail', '')
            if not thumb and isinstance(thumbs, list) and thumbs:
                thumb = thumbs[0].get('url', '')
            normalized.append({
                'video_id': vid,
                'title': item.get('title', ''),
                'channelTitle': item.get('channelTitle', item.get('artist', '')),
                'artist': item.get('artist', item.get('channelTitle', '')),
                'thumbnail': thumb,
                'duration': item.get('duration', ''),
            })
        return normalized

    def do_search(self, query):
        self.player.stop_radio()
        self.status_lbl.set_text('Buscando…')
        self.status_lbl.show()
        for row in self.list_box.get_children():
            self.list_box.remove(row)

        def search_thread():
            try:
                r = requests.get(f'{API_BASE}/search', params={'q': query, 'limit': 25}, timeout=10)
                if r.status_code == 200:
                    GLib.idle_add(self.display_results, self._normalize_results(r.json()))
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
            return False
        for item in results:
            row = SearchResultRow(item, self.player, self.thumb_loader)
            self.list_box.add(row)
        self.list_box.show_all()
        self.player.set_queue(results)
        return False

    def start_radio(self, query, label=None):
        self._radio_request_id += 1
        request_id = self._radio_request_id
        display_label = label or query
        self.radio_view.station_name.set_text('SINTONIZANDO…')
        self.radio_view.station_desc.set_text(f'Buscando una mezcla sólida para {display_label}.')
        self.radio_view.station_card.show_all()

        def radio_thread():
            try:
                r = requests.get(f'{API_BASE}/search', params={'q': query, 'limit': 40}, timeout=12)
                if request_id != self._radio_request_id:
                    return
                if r.status_code == 200:
                    results = self._normalize_results(r.json())
                    GLib.idle_add(self._activate_radio_results, results, display_label, request_id)
                else:
                    GLib.idle_add(self._radio_error, f'No pude crear la radio · Error {r.status_code}', request_id)
            except Exception as e:
                GLib.idle_add(self._radio_error, f'No pude crear la radio · {str(e)[:34]}', request_id)

        threading.Thread(target=radio_thread, daemon=True).start()

    def _activate_radio_results(self, results, label, request_id):
        if request_id != self._radio_request_id:
            return False
        if not results:
            return self._radio_error('No encontré suficientes canciones para esa estación.', request_id)
        self.radio_view.show_station(label, len(results))
        self.player.start_radio(results, label)
        return False

    def _radio_error(self, message, request_id):
        if request_id != self._radio_request_id:
            return False
        self.radio_view.station_name.set_text('RADIO NO DISPONIBLE')
        self.radio_view.station_desc.set_text(message)
        self.radio_view.station_card.show_all()
        return False

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
        elif key == Gdk.KEY_Left and not self.player.radio_mode:
            self.player.seek(max(0, self.player.get_position() - 5))
        elif key == Gdk.KEY_Right and not self.player.radio_mode:
            self.player.seek(self.player.get_position() + 5)
        elif key == Gdk.KEY_n and (event.state & Gdk.ModifierType.CONTROL_MASK):
            self.player.next()
            return True
        elif key == Gdk.KEY_r and (event.state & Gdk.ModifierType.CONTROL_MASK):
            self.mode_nav.activate('radio')
            return True
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
                json.dump({
                    'x': x,
                    'y': y,
                    'api_base': API_BASE,
                    'dl_dir': DL_DIR,
                    'last_mode': self._current_mode,
                }, f)
        except Exception:
            pass

    def load_config(self):
        global API_BASE, DL_DIR
        self.loaded_x = None
        self.loaded_y = None
        self.loaded_mode = 'music'
        try:
            if os.path.exists(CFG_FILE):
                with open(CFG_FILE) as f:
                    d = json.load(f)
                self.loaded_x = d.get('x')
                self.loaded_y = d.get('y')
                self.loaded_mode = d.get('last_mode', 'music')
                if 'api_base' in d:
                    API_BASE = d['api_base']
                if 'dl_dir' in d:
                    DL_DIR = d['dl_dir']
        except Exception:
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
    if app.loaded_mode == 'radio':
        app.mode_nav.activate('radio')
    if '--hidden' in sys.argv:
        app.hide_panel()
    else:
        app.show_panel()
    Gtk.main()
