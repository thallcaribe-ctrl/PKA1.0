"""Teste manual de entrada Win32. Sem OCR ou injecao no processo."""
import ctypes as c
from ctypes import wintypes as w
import sys
import json
import pydirectinput as direct
direct.PAUSE = 0.0
from pathlib import Path
import time

TIMING = {'key_hold_ms': 180, 'mouse_hold_ms': 150, 'mouse_move_ms': 220, 'mouse_settle_ms': 120}
TIMING_PATH = Path(__file__).with_name('tempos.json')
if TIMING_PATH.exists():
    try:
        values = json.loads(TIMING_PATH.read_text(encoding='utf-8-sig'))
        for key in TIMING:
            value = values.get(key, TIMING[key])
            if isinstance(value, (int, float)) and 30 <= value <= 2000:
                TIMING[key] = value
    except (ValueError, OSError, AttributeError) as error:
        print(f'Tempos invalidos; usando padrao: {error}', flush=True)

u = c.WinDLL('user32', use_last_error=True)
ULONG_PTR = c.c_size_t
class MOUSEINPUT(c.Structure):
    _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD), ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', ULONG_PTR)]
class KEYBDINPUT(c.Structure):
    _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', ULONG_PTR)]
class HARDWAREINPUT(c.Structure):
    _fields_ = [('uMsg', w.DWORD), ('wParamL', w.WORD), ('wParamH', w.WORD)]
class PAYLOAD(c.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]
class INPUT(c.Structure):
    _anonymous_ = ('payload',)
    _fields_ = [('type', w.DWORD), ('payload', PAYLOAD)]
u.GetForegroundWindow.restype = w.HWND
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.SendInput.argtypes = [w.UINT, c.POINTER(INPUT), c.c_int]
u.SendInput.restype = w.UINT
u.GetAsyncKeyState.argtypes = [c.c_int]
u.GetAsyncKeyState.restype = w.SHORT
u.MapVirtualKeyW.argtypes = [w.UINT, w.UINT]
u.MapVirtualKeyW.restype = w.UINT
u.GetCursorPos.argtypes = [c.POINTER(w.POINT)]
u.ScreenToClient.argtypes = [w.HWND, c.POINTER(w.POINT)]
u.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.SetCursorPos.argtypes = [c.c_int, c.c_int]


def game_window():
    hwnd = u.GetForegroundWindow()
    title = c.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, title, 512)
    return hwnd if title.value.lower().startswith('pokealliance - ') else None


def identity(hwnd):
    pid = w.DWORD()
    u.GetWindowThreadProcessId(hwnd, c.byref(pid))
    return hwnd, pid.value


def send(event):
    if u.SendInput(1, c.byref(event), c.sizeof(INPUT)) != 1:
        raise OSError(c.get_last_error(), 'Windows recusou o comando SendInput')


def keyboard(vk, hwnd):
    if game_window() != hwnd:
        return False
    name = {0x27: 'right', 0x25: 'left'}[vk]
    direct.keyDown(name)
    try:
        time.sleep(TIMING['key_hold_ms'] / 1000)
    finally:
        direct.keyUp(name)
    return True


def click_mark(mark, hwnd, right):
    if mark is None or identity(hwnd) != mark[:2]:
        print('Primeiro marque o alvo com F8 nesta janela.', flush=True)
        return False
    rect = w.RECT()
    if not u.GetClientRect(hwnd, c.byref(rect)) or (rect.right, rect.bottom) != mark[4:]:
        print('Tamanho da janela mudou. Marque novamente com F8.', flush=True)
        return False
    point = w.POINT(mark[2], mark[3])
    if not u.ClientToScreen(hwnd, c.byref(point)) or game_window() != hwnd:
        return False
    start = w.POINT()
    if not u.GetCursorPos(c.byref(start)):
        raise OSError('Nao foi possivel ler o cursor')
    steps = 20
    for step in range(1, steps + 1):
        if game_window() != hwnd or u.GetAsyncKeyState(0x7B) & 0x8000:
            return False
        fraction = step / steps
        smooth = fraction * fraction * (3 - 2 * fraction)
        x = round(start.x + (point.x - start.x) * smooth)
        y = round(start.y + (point.y - start.y) * smooth)
        direct.moveTo(x, y)
        time.sleep(TIMING['mouse_move_ms'] / 1000 / steps)
    time.sleep(TIMING['mouse_settle_ms'] / 1000)
    if game_window() != hwnd:
        return False
    button = 'right' if right else 'left'
    direct.mouseDown(button=button)
    try:
        time.sleep(TIMING['mouse_hold_ms'] / 1000)
    finally:
        direct.mouseUp(button=button)
    return True


def main():
    try:
        u.SetProcessDPIAware()
    except AttributeError:
        pass
    if '--click-test' in sys.argv:
        print('Em 5 segundos: deixe o jogo em primeiro plano e o mouse no ponto a clicar.', flush=True)
        print('Sera um unico clique ESQUERDO. Mova o mouse ao canto superior esquerdo para cancelar.', flush=True)
        for count in range(5, 0, -1):
            print(count, flush=True)
            time.sleep(1)
        hwnd = game_window()
        if not hwnd:
            title = c.create_unicode_buffer(512)
            u.GetWindowTextW(u.GetForegroundWindow(), title, 512)
            print(f'Cancelado: janela ativa nao reconhecida: {title.value!r}', flush=True)
            return
        point = w.POINT()
        rect = w.RECT()
        if not u.GetCursorPos(c.byref(point)) or not u.ScreenToClient(hwnd, c.byref(point)) or not u.GetClientRect(hwnd, c.byref(rect)):
            raise OSError('Falha ao ler posicao/janela')
        if not (0 <= point.x < rect.right and 0 <= point.y < rect.bottom):
            print('Cancelado: mouse fora do jogo.', flush=True)
            return
        mark = (*identity(hwnd), point.x, point.y, rect.right, rect.bottom)
        print('Clique enviado.' if click_mark(mark, hwnd, False) else 'Clique cancelado.', flush=True)
        return
    if '--check' in sys.argv:
        assert c.sizeof(INPUT) == (40 if c.sizeof(c.c_void_p) == 8 else 28)
        print('Estruturas Win32 e APIs OK. Nenhum comando enviado.')
        return
    print(f'Tempos (ms): {TIMING}', flush=True)
    print('POKEHUNT - TESTE MANUAL\nAbra o jogo e deixe a janela em primeiro plano.\nF6: passo para direita | F7: passo para esquerda\nF8: marcar posicao do mouse sobre o alvo\nF9: clique DIREITO no ponto marcado | F10: clique ESQUERDO\nF12: encerrar\nNao detecta inimigos. A marca e fixa e nao acompanha o Pokemon.\nNao ha repeticao automatica nem envio de R/1 nesta etapa.\n', flush=True)
    keys = list(range(0x75, 0x7A)) + [0x7B]
    previous = {key: bool(u.GetAsyncKeyState(key) & 0x8000) for key in keys}
    mark = None
    while True:
        for key in keys:
            pressed = bool(u.GetAsyncKeyState(key) & 0x8000)
            edge = pressed and not previous[key]
            previous[key] = pressed
            if not edge:
                continue
            if key == 0x7B:
                print('Encerrado.', flush=True)
                return
            hwnd = game_window()
            if not hwnd:
                print('Ignorado: PokeAlliance nao esta em primeiro plano.', flush=True)
                continue
            if key in (0x75, 0x76):
                if keyboard(0x27 if key == 0x75 else 0x25, hwnd):
                    print('Seta enviada. Confira o deslocamento no jogo.', flush=True)
            elif key == 0x77:
                point, rect = w.POINT(), w.RECT()
                if not u.GetCursorPos(c.byref(point)) or not u.ScreenToClient(hwnd, c.byref(point)) or not u.GetClientRect(hwnd, c.byref(rect)):
                    continue
                if 0 <= point.x < rect.right and 0 <= point.y < rect.bottom:
                    mark = (*identity(hwnd), point.x, point.y, rect.right, rect.bottom)
                    print(f'Ponto marcado: {point.x}, {point.y}.', flush=True)
            elif click_mark(mark, hwnd, key == 0x78):
                print('Clique enviado. Confira se selecionou o alvo.', flush=True)
        time.sleep(0.015)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f'Falha: {error}', flush=True)
        sys.exit(1)
