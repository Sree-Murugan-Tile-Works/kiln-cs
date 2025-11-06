

class Command:
	def __init__(self, cmd):
		"""
		Initialize and validate the command. Valid commands are:
			PID <sv>
			MAN <rpm>
			OFF

		:param command_string: The input command string
		:raises ValueError: If the command is invalid
		"""
		self.command = None
		self.value = None
		self._validate_and_parse(cmd.strip().upper())

	def _validate_and_parse(self, command: str):
		parts = command.split()

		command_type = parts[0]

		if command_type == "OFF":
			self.command = "OFF"
			self.value = None
			return

		if len(parts) < 2:
			raise ValueError(f"Invalid command format: '{command}'.")

		command_value = parts[1]

		if command_type == "PID":
			try:
				self.command = "PID"
				self.value = float(command_value)  # Attempt to convert value to a float
			except ValueError:
				raise ValueError(f"Invalid set_value for PID command: '{command_value}'.")

		elif command_type == "MAN":
			try:
				self.command = "MAN"
				self.value = int(command_value)  # Attempt to convert value to an integer
			except ValueError:
				raise ValueError(f"Invalid rpm for MAN command: '{command_value}'.")

		# If the command type is not recognized
		else:
			raise ValueError(f"Unknown command type: '{command_type}'.")


	def __str__(self):
		if self.command == "OFF":
			return self.command
		s = f"{self.command}:{self.value}"
		return s
