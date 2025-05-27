import numpy as np
import sounddevice as sd
import mido
import threading
import time
import tkinter as tk
from tkinter import filedialog

fs = 44100
buffer_size = 512

def note_to_freq(note):
    """MIDIノート番号を周波数(Hz)に変換"""
    return 440.0 * 2 ** ((note - 69) / 12)

class FMVoice:
    def __init__(self, freq, velocity):
        self.freq = freq
        self.velocity = velocity / 127
        self.phase = 0
        self.mod_phase = 0

        # 明るく高めの音色に調整
        self.mod_freq = freq * 2.0        # 2.0倍音に変更
        self.mod_index = 4.0 + 3.0 * self.velocity

        self.attack_time = 0.005
        self.decay_time = 0.1
        self.sustain_level = 0.6
        self.release_time = 0.2

        self.envelope_level = 0.0
        self.release_start_level = 0.0
        self.state = 'attack'
        self.dead = False

    def generate(self, num_samples):
        t = np.arange(num_samples) / fs
        modulator = np.sin(2 * np.pi * self.mod_freq * t + self.mod_phase) * self.mod_index
        carrier = np.sin(2 * np.pi * self.freq * t + self.phase + modulator)

        envelope = np.zeros(num_samples)
        for i in range(num_samples):
            if self.state == 'attack':
                self.envelope_level += 1.0 / (self.attack_time * fs)
                if self.envelope_level >= 1.0:
                    self.envelope_level = 1.0
                    self.state = 'decay'
            elif self.state == 'decay':
                self.envelope_level -= (1.0 - self.sustain_level) / (self.decay_time * fs)
                if self.envelope_level <= self.sustain_level:
                    self.envelope_level = self.sustain_level
                    self.state = 'sustain'
            elif self.state == 'sustain':
                pass
            elif self.state == 'release':
                self.envelope_level -= self.release_start_level / (self.release_time * fs)
                if self.envelope_level <= 0:
                    self.envelope_level = 0
                    self.dead = True
            envelope[i] = self.envelope_level

        output = carrier * envelope * self.velocity * 0.6

        self.phase += 2 * np.pi * self.freq * num_samples / fs
        self.phase %= 2 * np.pi
        self.mod_phase += 2 * np.pi * self.mod_freq * num_samples / fs
        self.mod_phase %= 2 * np.pi

        return output

    def note_off(self):
        if self.state != 'release':
            self.release_start_level = self.envelope_level
            self.state = 'release'

    def is_dead(self):
        return self.dead

class MidiFMPlayer:
    def __init__(self, midi_file):
        self.midi = mido.MidiFile(midi_file)
        self.voices = []
        self.lock = threading.Lock()
        self.playing = False

    def play_midi(self):
        for msg in self.midi.play():
            if not self.playing:
                break
            if msg.type == 'note_on' and msg.velocity > 0:
                freq = note_to_freq(msg.note)
                voice = FMVoice(freq, msg.velocity)
                with self.lock:
                    self.voices.append(voice)
            elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                freq = note_to_freq(msg.note)
                with self.lock:
                    for v in self.voices:
                        if abs(v.freq - freq) < 1e-3:
                            v.note_off()
        with self.lock:
            for v in self.voices:
                v.note_off()
        time.sleep(2)
        self.playing = False

    def audio_callback(self, outdata, frames, time_info, status):
        buffer = np.zeros(frames, dtype=np.float32)
        with self.lock:
            new_voices = []
            for voice in self.voices:
                buffer += voice.generate(frames)
                if not voice.is_dead():
                    new_voices.append(voice)
            self.voices = new_voices
        # モノラルbufferをステレオにコピー
        stereo_buffer = np.column_stack((buffer, buffer))
        outdata[:] = stereo_buffer

    def start(self):
        self.playing = True
        thread = threading.Thread(target=self.play_midi)
        thread.start()
        with sd.OutputStream(channels=2, samplerate=fs,
                             blocksize=buffer_size, callback=self.audio_callback):
            while self.playing:
                time.sleep(0.1)

if __name__ == "__main__":
    # tkinterでファイル選択ダイアログ表示
    root = tk.Tk()
    root.withdraw()  # メインウィンドウを隠す

    midi_file = filedialog.askopenfilename(
        title="MIDIファイルを選択してください",
        filetypes=[("MIDI files", "*.mid *.midi")]
    )

    if not midi_file:
        print("ファイルが選択されませんでした。終了します。")
        exit()

    player = MidiFMPlayer(midi_file)
    print("演奏開始")
    player.start()
    print("演奏終了")
