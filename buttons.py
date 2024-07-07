import adafruit_logging as logging
log = logging.getLogger()
from keypad import Keys
from microcontroller import Pin
import supervisor
# import asyncio

class _ButtonData():
	def __init__(self, key_number: int, pin: Pin):
		self.key_number = key_number
		self.pin = pin
		self.presses = 0
		self.pressed_ts: None | int = None
		self.released_ts: None | int = None

	def __repr__(self) -> str:
		return f"ButtonData<Pin={self.pin}, #{self.presses} from {self.pressed_ts} to {self.released_ts}>"

class Buttons():
	def __init__(self,
					pins: dict[Pin, bool],
					short_press_threshold_ms: int = 500,  # Set to 0 to disable multi-presses
					long_press_threshold_ms: int = 2000,   # Set to 0 to disable long presses
				):
		self.pressed_pins = set()
		self.pins = pins
		self.callbacks = {}

		self.keys: dict[Keys, list[Pin]] = {}

		for boolVal in [True, False]:
			relevant_pins = [pin[0] for pin in pins.items() if boolVal == pin[1]]
			if len(relevant_pins) > 0:
				self.keys[Keys(relevant_pins, value_when_pressed = boolVal)] = relevant_pins

		self.pressed_keys: dict[Pin, _ButtonData] = dict()
		self.short_press_threshold_ms = short_press_threshold_ms
		self.long_press_threshold_ms = long_press_threshold_ms

	# Looks at the keys array to see which further presses and releases has occured, and
	# records them for later review.
	def detect_button_presses(self):
		for keys, pins in self.keys.items():
			while True:
				event = keys.events.get()
				if not event:
					break

				pin = pins[event.key_number]

				if event.pressed:
					self.pressed_pins.add(pin)
					multi_key_callback = self.callbacks.get(tuple(self.pressed_pins))
					if multi_key_callback != None:
						for pin in self.pressed_pins:
							if pin in self.pressed_keys:
								del self.pressed_keys[pin]
							self.pressed_pins.remove(pin)
						multi_key_callback(self.pressed_pins)
						break

				if event.released and pin in self.pressed_pins:
					self.pressed_pins.remove(pin)

				if event.pressed and pin not in self.pressed_keys:
					data = _ButtonData(event.key_number, pin)
					self.pressed_keys[pin] = data

				if event.released and pin in self.pressed_keys and self.pressed_keys[pin].pressed_ts != None:
					self.pressed_keys[pin].released_ts = event.timestamp
					log.debug(f"Key released. Pin: {self.pressed_keys[pin].pin}, Presses: {self.pressed_keys[pin].presses}, TS: {self.pressed_keys[pin].released_ts}")
				elif event.pressed:
					self.pressed_keys[pin].presses += 1
					self.pressed_keys[pin].pressed_ts = event.timestamp
					self.pressed_keys[pin].released_ts = None
					log.debug(f"Key pressed. Pin: {self.pressed_keys[pin].pin}, Presses: {self.pressed_keys[pin].presses}, TS: {self.pressed_keys[pin].pressed_ts}")

	# Looks at the current list of recorded key presses, and see if enough time has passed
	# since the last press or release to determine that a series of short presses has concluded,
	# optionally ending with a long press.
	def handle_button_presses(self):
		for key, btn in self.pressed_keys.items():
			if btn.pressed_ts != None and btn.released_ts == None:
				# The button is currently being depressed. Is it a long press?
				if supervisor.ticks_ms() - btn.pressed_ts > self.long_press_threshold_ms:
					# Long press detected!
					del self.pressed_keys[key]
					self.execute_button_press((btn.pin, btn.presses, True))
					# Only execute one action per loop to allow for resets to take effect
					return

			elif btn.pressed_ts != None and btn.released_ts != None:
				# We have a press and release. Has enough time passed to act on it?
				if supervisor.ticks_ms() - btn.released_ts > self.short_press_threshold_ms:
					# Short press detected!
					del self.pressed_keys[key]
					self.execute_button_press((btn.pin, btn.presses, False))
					# Only execute one action per loop to allow for resets to take effect
					return

	def loop(self):
		"Return true if any keys are busy, meaning keypresses have been registered but not yet executed."
		self.detect_button_presses()
		self.handle_button_presses()
		return len(self.pressed_keys) > 0

	def set_callback(self, pin: Pin, presses = 1, long_press=False, callback: callable[[Pin, int, bool]: None] | None = None):
		key = (pin, presses, long_press)
		if callback == None:
			del self.callbacks[key]
		else:
			self.callbacks[key] = callback

	def set_callback_multikey(self, pins: set[Pin], callback: callable[[set[Pin]]: None] | None = None):
		key = tuple(pins)
		if callback == None:
			del self.callbacks[key]
		else:
			self.callbacks[key] = callback

	def set_fallback(self, callback: callable[[Pin, int, bool]: None] | None = None):
		if callback == None:
			del self.callbacks[None]
		else:
			self.callbacks[None] = callback

	def execute_button_press(self, key: tuple[Pin, int, bool]):
		cb = self.callbacks.get(key)
		if cb == None:
			cb = self.callbacks.get(None)
		if cb != None:
			cb(*key)

	def clear_callbacks(self):
		for key in self.callbacks.keys():
			log.debug(f'Remove key: {key}')
			del self.callbacks[key]