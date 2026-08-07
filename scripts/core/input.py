from __future__ import annotations

import pygame.key
import pygame.joystick

from config.managers.core_data import CoreAsset

KEYBOARD = {
    "a": pygame.K_a, "b": pygame.K_b, "c": pygame.K_c, "d": pygame.K_d,
    "e": pygame.K_e, "f": pygame.K_f, "g": pygame.K_g, "h": pygame.K_h,
    "i": pygame.K_i, "j": pygame.K_j, "k": pygame.K_k, "l": pygame.K_l,
    "m": pygame.K_m, "n": pygame.K_n, "o": pygame.K_o, "p": pygame.K_p,
    "q": pygame.K_q, "r": pygame.K_r, "s": pygame.K_s, "t": pygame.K_t,
    "u": pygame.K_u, "v": pygame.K_v, "w": pygame.K_w, "x": pygame.K_x,
    "y": pygame.K_y, "z": pygame.K_z,
    "space": pygame.K_SPACE,
    "left_shift": pygame.K_LSHIFT,
    "right_shift": pygame.K_RSHIFT,
    "left_ctrl": pygame.K_LCTRL,
    "right_ctrl": pygame.K_RCTRL,
    "left_alt": pygame.K_LALT,
    "right_alt": pygame.K_RALT,
    "tab": pygame.K_TAB,
    "backspace": pygame.K_BACKSPACE,
    "enter": pygame.K_RETURN,
    "escape": pygame.K_ESCAPE,
    "up": pygame.K_UP,
    "down": pygame.K_DOWN,
    "left": pygame.K_LEFT,
    "right": pygame.K_RIGHT
}

CONTROLLER = {
    "up": 0, "down": 1, "left": 2, "right": 3,
    "a": 4, "b": 5, "x": 6, "y": 7,
    "left_bumper": 8, "right_bumper": 9,
    "left_trigger": 10, "right_trigger": 11,
    "back": 12, "start": 13
}

# Raw index aliases. config/inputs.json binds "gamepad:button_0", "button_1"
# and "button_9", none of which existed in CONTROLLER -- those bindings were
# silently dead. pygame's Joystick.get_button() takes a raw index anyway, so
# button_N maps straight through.
CONTROLLER.update({f"button_{i}": i for i in range(16)})


class UnknownBindingError(KeyError):
    """A config binding names a key or button this engine does not know."""


class BaseAction:
    """One named action ("left", "attack") and the inputs bound to it.

    The three state flags are read once per frame by InputActionManager.update:
        held     - the action is down right now (continuous)
        pressed  - it went down on THIS frame only (rising edge)
        released - it came up on THIS frame only (falling edge)
    """

    def __init__(self, action_type: str, raw_input: list[str]):
        self.action_type = action_type
        # split and assign the input type and key
        self.inputs: list[tuple[str, str]] = [ (inpu.split(":")[0], inpu.split(":")[1]) for inpu in raw_input ]
        self.pressed = False
        self.released = False
        self.held = False


class InputActionManager(CoreAsset):

    def __init__(self):
        self.actions = {}
        self.config = None
        self.gamepad = None
        self.keyboard = None

    def update(self):
        """Sample every action once and derive this frame's edges.

        Edges are derived by comparing the raw state against last frame's
        `held`, which is the only way `released` can be a real falling edge.
        The previous implementation guarded each flag behind its own value
        (`if action and not action.released`), so `released` latched True on
        the first frame and never cleared -- `released('pause')` fired every
        frame from startup forever.
        """
        if not self.config:
            return
        self.keyboard = pygame.key.get_pressed()
        for action in self.actions.values():
            down = self._is_down(action)
            action.pressed = down and not action.held
            action.released = action.held and not down
            action.held = down

    def pressed(self, action_name: str) -> bool:
        """True only on the frame the action went down. Use for menus, jumps."""
        return self.actions[action_name].pressed

    def released(self, action_name: str) -> bool:
        """True only on the frame the action came up."""
        return self.actions[action_name].released

    def held(self, action_name: str) -> bool:
        """True for every frame the action is down. Use for movement."""
        return self.actions[action_name].held

    def _is_down(self, action: BaseAction) -> bool:
        """True if ANY input bound to this action is currently down.

        One scan per action per frame. The old _pressed/_released/_held trio
        each re-called pygame.key.get_pressed() per binding, and _released
        used `not pressed` per binding -- so with two bindings on one action,
        holding either one reported the action as simultaneously held and
        released, because the other binding was up.
        """
        for input_type, key in action.inputs:
            if input_type in ("keyboard", "key"):
                code = KEYBOARD.get(key)
                if code is None:
                    raise UnknownBindingError(
                        f"action {action.action_type!r} binds unknown keyboard key {key!r}; "
                        f"valid keys: {sorted(KEYBOARD)}"
                    )
                if self.keyboard[code]:
                    return True
            elif input_type in ("gamepad", "controller"):
                if self.gamepad is None:
                    continue
                button = CONTROLLER.get(key)
                if button is None:
                    raise UnknownBindingError(
                        f"action {action.action_type!r} binds unknown gamepad button {key!r}; "
                        f"valid buttons: {sorted(CONTROLLER)}"
                    )
                if self.gamepad.get_button(button):
                    return True
        return False

    def prepare_inputs(self, rebind: dict | None = None) -> InputActionManager:
        if len(self.actions) > 0:
            self.actions.clear()
        if rebind:
            self.config = rebind
        for action_name, action_input in self.config.items():
            self.actions[action_name] = BaseAction(action_name, action_input)
        self.validate_bindings()
        # Deliberately NOT sampling the keyboard here: prepare_inputs runs from
        # CoreAssetManager.__init__, which main.py calls before
        # pygame.display.set_mode(), and pygame.key.get_pressed() requires an
        # initialized video mode. Every action starts held=False, so the first
        # update() already computes correct edges without priming.
        return self

    def validate_bindings(self):
        """Fail loudly at load time on an unknown key or malformed binding.

        Without this a typo in inputs.json surfaces as a TypeError deep in the
        per-frame scan (`get_pressed()[None]`), or silently never fires.
        """
        for action in self.actions.values():
            for input_type, key in action.inputs:
                if input_type in ("keyboard", "key"):
                    if key not in KEYBOARD:
                        raise UnknownBindingError(
                            f"action {action.action_type!r} binds unknown keyboard key {key!r}"
                        )
                elif input_type in ("gamepad", "controller"):
                    if key not in CONTROLLER:
                        raise UnknownBindingError(
                            f"action {action.action_type!r} binds unknown gamepad button {key!r}"
                        )
                else:
                    raise UnknownBindingError(
                        f"action {action.action_type!r} uses unknown input type {input_type!r}; "
                        f"expected one of: keyboard, key, gamepad, controller"
                    )

    def set_gamepad(self):
        self.gamepad = pygame.joystick.Joystick(0)
        self.gamepad.init()

    def load_assets(self, name: str):
        pass

    def unload_assets(self, name: str):
        pass

    def reload(self, config: dict[str, any] | tuple[str, any]):
        pass

    def prepare(self, config: dict[str, any]) -> InputActionManager:
        return self.prepare_inputs(config)
