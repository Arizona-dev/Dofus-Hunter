import tkinter as tk
from tkinter import scrolledtext
import pyautogui
import threading
import json
import os
import json
import base64
import pyperclip
import random
import re
import pytesseract
import pygame
from fuzzywuzzy import fuzz
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv
from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pywinauto.keyboard import send_keys
from charset_normalizer import from_bytes

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

load_dotenv()

CONFIG_FILE = "config.json"


class RegionSelector(tk.Toplevel):
    """
    Semi-transparent overlay for selecting a screen region.
    Press Esc at any time to cancel.
    """

    def __init__(self, master, prompt_text="Select Region"):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.5)

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")

        self.canvas = tk.Canvas(self, bg="gray", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Large red label centered on the canvas
        self.canvas.create_text(
            screen_w // 2,
            screen_h // 2,
            text=prompt_text,
            fill="red",
            font=("Arial", 28, "bold"),
        )

        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.selected_region = None
        self.canceled = False

        # Bind mouse events
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        # Bind Escape to cancel
        self.bind("<Escape>", self.on_escape)

    def on_button_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline="red",
            width=2,
        )

    def on_move_press(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        x1, x2 = sorted([self.start_x, end_x])
        y1, y2 = sorted([self.start_y, end_y])
        self.selected_region = (x1, y1, x2 - x1, y2 - y1)
        self.destroy()

    def on_escape(self, event):
        self.canceled = True
        self.destroy()


class DofusTreasureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dofus Treasure Hunt Helper")
        self.attributes("-topmost", True)
        self.selenium_driver = None
        self.hunt_started = False
        self.last_travel_cmd = None
        self.is_first_hint = True
        self.hintDirection = None
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.last_hint_coords = None

        # Position near top-right
        self.configure(bg="#2E2E2E")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        app_w, app_h = 460, 550
        # default center of the screen
        offset_x = (screen_w - app_w) // 2
        offset_y = (screen_h - app_h) // 2

        self.config_data = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                self.config_data = json.load(f)
                offset_x = (
                    self.config_data["treasure_region"]["x"]
                    + self.config_data["treasure_region"]["width"]
                    + 10
                )
                offset_y = self.config_data["treasure_region"]["y"]
                offset_x = min(offset_x, screen_w - app_w)
                offset_y = min(offset_y, screen_h - app_h)

        self.geometry(f"{app_w}x{app_h}+{offset_x}+{offset_y}")

        self.main_frame = tk.Frame(self, bg="#2E2E2E")
        self.main_frame.pack(expand=True, fill=tk.BOTH)

        self.button_row = tk.Frame(self.main_frame, bg="#2E2E2E")
        self.direction_pad = tk.Frame(self.main_frame, bg="#2E2E2E")
        self.direction_middle = tk.Frame(self.direction_pad, bg="#2E2E2E")
        self.log_frame = tk.Frame(self.main_frame, bg="#2E2E2E")

        self.heading_label = tk.Label(
            self.button_row,
            text="Dofus Treasure Hunt",
            font=("Arial", 12, "bold"),
            fg="white",
            bg="#2E2E2E",
        )

        self.separator = tk.Frame(self.main_frame, height=2, bg="gray")

        self.setup_button = tk.Button(
            self.button_row,
            text="Setup",
            font=("Arial", 12, "bold"),
            bg="#4F4F4F",
            fg="white",
            command=self.run_setup,
        )

        self.start_hunt_button = tk.Button(
            self.main_frame,
            text="Start Hunt",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=self.start_hunt,
        )

        # Create buttons for each direction
        self.north_button = tk.Button(
            self.main_frame,
            text="↑ North",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=lambda: self.force_hint_direction(6),
        )

        self.west_button = tk.Button(
            self.main_frame,
            text="← West",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=lambda: self.force_hint_direction(4),
        )

        self.east_button = tk.Button(
            self.main_frame,
            text="→ East",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=lambda: self.force_hint_direction(0),
        )

        self.south_button = tk.Button(
            self.main_frame,
            text="↓ South",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=lambda: self.force_hint_direction(2),
        )

        self.end_hunt_button = tk.Button(
            self.button_row,
            text="End Hunt",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=self.end_hunt,
        )

        # Display current direction
        self.direction_label = tk.Label(
            self.main_frame,
            text="-",
            font=("Arial", 12),
        )

        self.info_label = tk.Label(
            self.main_frame,
            text="",
            wraplength=260,
            fg="white",
            bg="#2E2E2E",
            font=("Arial", 10),
        )

        self.clear_log_button = tk.Button(
            self.log_frame,
            text="Clear Log",
            font=("Arial", 12),
            bg="#FF6347",
            fg="white",
            command=self.clear_log,
        )

        # Add log display
        self.log_display = scrolledtext.ScrolledText(
            self.log_frame, wrap=tk.WORD, state="disabled", height=1
        )

        if self.is_config_valid():
            self.place_widgets()

        self.initialize_selenium()

    def place_widgets(self):
        # Heading Label
        self.heading_label.pack(fill=tk.X, pady=10)

        # Row for Start Hunt and Setup Buttons
        self.separator.pack(in_=self.button_row, fill=tk.X, pady=(0, 20))
        self.start_hunt_button.pack(in_=self.button_row, side=tk.LEFT, expand=tk.TRUE)
        self.end_hunt_button.pack(in_=self.button_row, side=tk.LEFT, expand=tk.TRUE)
        self.setup_button.pack(in_=self.button_row, side=tk.RIGHT, expand=tk.TRUE)
        self.button_row.pack(pady=0, fill=tk.X)

        # Separation line

        # Direction buttons
        self.direction_pad.pack(pady=(20, 10))

        self.north_button.pack(in_=self.direction_pad, pady=(0, 10))
        self.direction_middle.pack()
        self.west_button.pack(in_=self.direction_middle, side="left", padx=(10, 20))
        self.direction_label.pack(in_=self.direction_middle, side="left", padx=20)
        self.east_button.pack(in_=self.direction_middle, side="right", padx=(20, 10))
        self.south_button.pack(in_=self.direction_pad, pady=10)

        # Log Display and Clear Button
        self.log_frame.pack(fill=tk.BOTH, expand=True, pady=0)
        self.log_display.pack(
            fill=tk.BOTH, expand=True, side="top", padx=10, pady=(0, 5)
        )
        self.clear_log_button.pack(fill=tk.X, side="bottom", padx=10, pady=(5, 0))

    def end_hunt(self):
        if hasattr(self, "end_hunt_button"):
            self.end_hunt_button.config(state=tk.DISABLED)
            self.log_message("Hunt ended.", "red")
        else:
            self.log_message("End hunt button not initialized.", "red")
        self.hunt_started = False
        self.last_hint_coords = None
        self.last_travel_cmd = None
        self.is_first_hint = True
        self.hintDirection = None
        self.selenium_driver.refresh()
        self.log_message("Hunt ended.", "green")

    def force_hint_direction(self, direction):
        self.hintDirection = direction

        # convert 0, 2, 4, 6 to N, S, W, E
        direction = {0: "East", 2: "South", 4: "West", 6: "North"}[direction]

        self.direction_label.config(text=f"{direction}")
        self.log_message(f"Hint Direction forced to: {direction}", "blue")
        self.start_hunt()

    def on_closing(self):
        # Close Selenium WebDriver if initialized
        if self.selenium_driver:
            self.selenium_driver.quit()

        # Destroy the Tkinter window
        self.destroy()

    def clear_log(self):
        """
        Clear the log display.
        """
        self.log_display.configure(state="normal")
        self.log_display.delete(1.0, tk.END)
        self.log_display.configure(state="disabled")

    def log_message(self, message, color="black"):
        """
        Log a message to the log display with the specified color.
        """
        self.log_display.configure(state="normal")

        # Generate a unique tag for this message
        tag_name = f"tag_{len(self.log_display.get('1.0', tk.END).splitlines())}"

        # Insert the message
        self.log_display.insert(tk.END, message + "\n", (tag_name,))

        # Configure the tag with the specified color
        self.log_display.tag_configure(tag_name, foreground=color)

        # Auto-scroll to the latest log
        self.log_display.see(tk.END)

        self.log_display.configure(state="disabled")

    def is_config_valid(self):
        required = ["player_region", "treasure_region", "chat_region"]
        return all(k in self.config_data for k in required)

    def run_setup(self):
        """
        Ask for 3 regions in order:
         1) Player coordinate region
         2) Treasure hunt region
         3) Chat input region
        Press Esc at any point to cancel the entire setup.
        """
        self.setup_button.pack_forget()
        self.start_hunt_button.pack_forget()
        self.end_hunt_button.pack_forget()
        self.info_label.config(
            text="Follow prompts to select each region. Press Esc to cancel."
        )

        # 1) Player coordinate region
        if not self.select_region("player_region", "Select Player Coordinate Region"):
            self.setup_cancel()
            return

        # 2) Treasure hunt region
        if not self.select_region("treasure_region", "Select Treasure Hunt Region"):
            self.setup_cancel()
            return

        # 3) Chat input region
        if not self.select_region("chat_region", "Select Chat Input Region"):
            self.setup_cancel()
            return

        # Save config
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config_data, f, indent=2)

        if self.is_config_valid():
            self.info_label.config(text="Setup complete. You can now start the hunt.")
            self.place_widgets()

    def setup_cancel(self):
        """
        Restores the setup button if the user cancels.
        """
        self.setup_button.pack(pady=5)
        self.info_label.config(text="Setup canceled.")

    def select_region(self, key_name, prompt_text):
        """
        Shows the RegionSelector overlay to pick a region.
        Returns False if user pressed Escape, otherwise True.
        """
        self.withdraw()

        selector = RegionSelector(self, prompt_text=prompt_text)
        selector.lift()
        selector.grab_set()
        selector.focus_force()

        selector.wait_window()
        self.deiconify()

        if selector.canceled:
            return False

        if selector.selected_region:
            x, y, w, h = selector.selected_region
            self.config_data[key_name] = {"x": x, "y": y, "width": w, "height": h}
            return True

        return False

    def initialize_selenium(self):
        chrome_options = Options()
        # chrome_options.add_argument("--headless")  # Run in the background
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0"
        )
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        try:
            driver = webdriver.Chrome(options=chrome_options)
            screen_width = driver.execute_script("return screen.availWidth;")
            screen_height = driver.execute_script("return screen.availHeight;")
            x_position = (screen_width - 1024) // 2
            y_position = (screen_height - 768) // 2
            driver.set_window_position(x_position, y_position)

            # Open the website
            file_path = os.path.abspath("./dofus_hints/index.html")
            driver.get(f"file://{file_path}")
            self.selenium_driver = driver
        except Exception as e:
            self.log_message(f"Failed to initialize Selenium: {e}", "red")
            self.selenium_driver = None

    def play_with_volume(self, file):
        """
        Play an audio file with a specified volume.

        :param file: Path to the audio file
        :param volume: Volume level (0.0 to 1.0)
        """
        volume = 0.2
        pygame.mixer.init()
        pygame.mixer.music.load(file)
        pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            continue

    def start_hunt(self):
        if not self.selenium_driver:
            return
        if not self.hunt_started:
            self.start_hunt_button.config(state=tk.NORMAL)
            self.end_hunt_button.config(state=tk.NORMAL)
            self.start_hunt_button.config(text="Next Hint")
            self.hunt_started = True
        self.next_hint()

    def next_hint(self):
        if self.hunt_started is False:
            return

        def do_hunt():
            try:
                self.log_message("Searching new hint...")
                self.start_hunt_button.config(state=tk.DISABLED)

                treasure_region = self.config_data["treasure_region"]
                region_tuple = (
                    treasure_region["x"],
                    treasure_region["y"],
                    treasure_region["width"],
                    treasure_region["height"],
                )
                # Sending to GPT
                screenshot = pyautogui.screenshot(region=region_tuple)
                self.log_message("Sending hint to GPT...")
                response_data = self.send_to_chatgpt(screenshot)
                data = json.loads(response_data)

                required_fields = [
                    "startPos",
                    "startPosDescription",
                    "hints",
                    "step",
                    "totalSteps",
                ]
                missing_fields = [
                    field for field in required_fields if field not in data
                ]
                if missing_fields:
                    self.log_message(
                        f"Error: Missing fields response: {missing_fields}", "red"
                    )
                    self.log_message("-" * 40)
                    self.log_message(f"Received response: {data}", "red")
                    self.start_hunt_button.config(state=tk.NORMAL)
                    # self.next_hint()
                    return

                # Check if hints exist and are valid
                if not data["hints"] or not isinstance(data["hints"], list):
                    self.log_message(
                        "Error: No hints provided in response. Retrying...", "red"
                    )
                    self.next_hint()
                    return

                # Retrieve the last hint
                last_hint = data["hints"][-1]

                if self.hintDirection is not None:
                    last_hint["hintDirection"] = self.hintDirection

                if "hintText" not in last_hint or "hintDirection" not in last_hint:
                    self.log_message(
                        "Error: Invalid hint structure in response. Retrying...", "red"
                    )
                    self.log_message(f"Received hints: {data['hints']}", "red")
                    self.next_hint()
                    return

                # Check if hintText is valid
                if last_hint["hintText"] == "?" or not last_hint["hintText"]:
                    self.log_message("No hint found. Retrying...", "red")
                    self.next_hint()
                    return

                # Save progression to JSON
                self.save_progression(data.get("startPosDescription"), data)

                # If it's not the first hint, get current player position
                if self.is_first_hint:
                    self.log_message("Retrieving current player position...")
                    current_x, current_y = self.get_current_player_position()
                    if current_x is None or current_y is None:
                        self.log_message(
                            "Failed to retrieve player position. Retrying...", "red"
                        )
                        self.next_hint()
                        return
                    data["startPos"] = [current_x, current_y]

                if self.hintDirection is None:
                    # Validate hintDirection
                    valid_directions = {0, 2, 4, 6}
                    if last_hint["hintDirection"] not in valid_directions:
                        self.log_message(
                            f"Invalid hintDirection: {last_hint['hintDirection']}. Retrying...",
                            "red",
                        )
                        self.next_hint()
                        return

                # Check if the coordinates are far from the last hint coordinates. If yes there is a chance that the hint is wrong.
                if self.last_hint_coords is not None:
                    distance = abs(
                        self.last_hint_coords[0] - data["startPos"][0]
                    ) + abs(self.last_hint_coords[1] - data["startPos"][1])
                    if distance > 10:
                        self.log_message(
                            f"Distance between last hint and current hint is {distance}. Retrying...",
                            "red",
                        )
                        self.next_hint()
                        return
                else:
                    # Setting new hunt position
                    self.last_travel_cmd = (
                        f"/travel {data['startPos'][0]} {data['startPos'][1]}"
                    )

                # Input data into hint finder
                self.log_message("Searching hint...")
                travel_cmd = self.input_dofus_hint(data)
                if travel_cmd is None:
                    self.log_message(
                        "You can try again by clicking 'Next Hint'.", "red"
                    )
                    self.start_hunt_button.config(state=tk.NORMAL)
                    self.play_with_volume("./assets/error.wav")
                    return

                # Check clipboard for /travel
                self.log_message(f"Generated Travel command: {travel_cmd}")

                if travel_cmd == self.last_travel_cmd:
                    self.log_message(
                        "Aborting: Already at this pos. Try again by clicking 'Next Hint'.",
                        "red",
                    )
                    self.start_hunt_button.config(state=tk.NORMAL)
                    return

                # Update the last travel command
                self.last_travel_cmd = travel_cmd

                # Paste the /travel command
                self.input_travel_command(travel_cmd)
                pyperclip.copy(travel_cmd)
                # Reset the UI
                self.start_hunt_button.config(state=tk.NORMAL)
                self.hintDirection = None
            except Exception as e:
                self.log_message(f"Error during hunt: {e}", "red")
                self.start_hunt_button.config(state=tk.NORMAL)

        threading.Thread(target=do_hunt).start()

    def auto_detect_and_fix(self, text):
        try:
            detected = from_bytes(text.encode()).best()
            return str(detected)
        except Exception as e:
            return text  # Return original if detection fails

    def upscale_to_1080p_and_encode(self, image, playerPos=False):
        """
        Upscale the image to 1080p (keeping aspect ratio),
        and returns the Base64-encoded string of the result.

        Args:
            region_tuple (tuple): A tuple specifying the region (x, y, width, height).

        Returns:
            str: Base64-encoded string of the upscaled screenshot.
        """
        screenshot = image
        screenshot.save("last_screenshot.png")

        # Convert screenshot to a PIL image
        img = screenshot.convert("RGB")

        # Get original dimensions
        original_width, original_height = img.size

        # Calculate the scaling factor to upscale while keeping aspect ratio
        target_height = 1080
        scaling_factor = target_height / original_height
        target_width = int(original_width * scaling_factor)

        # Resize the image with the calculated dimensions
        img_resized = img.resize((target_width, target_height), Image.LANCZOS)

        if playerPos is False:
            img_resized.save("upscaled_screenshot.png")
        # Save the resized image to a BytesIO buffer
        buffer = BytesIO()
        img_resized.save(buffer, format="PNG")
        buffer.seek(0)  # Move cursor to the start of the buffer

        # Convert the image to Base64
        base64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return base64_str

    def send_to_claude(self, image, getPlayerPos=False):
        img_b64_str = self.upscale_to_1080p_and_encode(image, getPlayerPos)
        img_type = "image/png"

        prompt = """You are an AI assistant specialized in parsing Dofus treasure hunt hint images. Your task is to analyze the provided image and extract specific information, then return it in a structured JSON format. Follow these instructions carefully:

        1. You will be provided with one image, from dofus treasure hunt.
        Each hint line in the image contains the following information:
        - Direction of the hint (hintDirection)
        - Text of the hint (hintText)
        - State of the hint eg: EN COURS or VALIDÉ.
        - Pin icon on the right of the hint eg: white pin.

        2. Analyze the treasure_hunt_image to extract the following information:
        a. Starting position coordinates (startPos)
        b. Map description (startPosDescription)
        c. List of hints containing the following information:
            a. Direction of the hint (hintDirection)
            b. Text of the hint (hintText)
        d. Current step number (step)
        e. Total number of steps (totalSteps)

        3. When parsing the image, follow these guidelines:
        - The starting position is indicated by "Départ [x, y]".
        - The map description is the text in parentheses below the starting position.
        - Always return the last hint in the list, don't mix up the hints.
        - Ignore question marks "?" in the hint text.
        - Double-check coordinates for negative signs.
        - Double-check the direction you saw of each hint in the list.

        4. For the hint direction my app has to receive a number. For each hint, the direction of the arrow on the left of the hint list should be converted to a number:
        - Right = 0
        - Down = 2
        - Left = 4
        - Up = 6

        5. Format your response as a JSON object with the following structure:
        Return the hints in the JSON object in the order they appear in the image.
        {
            "startPos": [int, int],
            "startPosDescription": "string",
            "hints": [
                "hintDirection": int,
                "hintText": "string", (Should not contain EN COURS or VALIDÉ)
                "completeHint": "hintDirection hintText",
            ],
            "step": int,
            "totalSteps": int,
            "isFirstHint": bool,
        }

        6. If you cannot clearly read or determine any of the required information, use null for that field in the JSON output.

        7. Do not include any explanations, comments, or additional text outside of the JSON object in your response."""

        getPlayerPosPrompt = """You are an AI assistant specialized in parsing Dofus player coordinates images. Your task is to analyze the provided image and extract the player's current position, then return it in a structured JSON format. Follow these instructions carefully: 
        
        1. You will be provided with an image containing Dofus player coordinates.
        
        2. Analyze the player_coordinates_image to extract the following information:
        a. Player's current position coordinates (playerPos) as [x, y]. Ignore any other information in the image.
        
        3. When parsing the image, follow these guidelines:
        - The player's coordinates are shown as numbers on the image.
        Always double check the reading of the coordinates.
        
        4. Format your response as a JSON object with the following structure:
        {
            "playerPos": [int, int] (should not contain any other information than the coordinates) and no -Ni
        }
        
        5. Do not include any explanations, comments, or additional text outside of the JSON object in your response.
        
        Analyze the provided images and return only the JSON object as described above."""

        client = Anthropic()

        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img_type,
                                "data": img_b64_str,
                            },
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": getPlayerPosPrompt if getPlayerPos else prompt,
                        }
                    ],
                },
            ],
            stream=False,
        )

        self.log_message(f"Claude Response: {message.content[0].text}")
        return message.content[0].text

    def send_to_chatgpt(self, image, getPlayerPos=False):
        return self.send_to_claude(image, getPlayerPos)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        img_b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
        img_type = "image/png"

        gpt_prompt = """[Roles: Treasure Hunt Expert]
            When presented with an image containing a Dofus treasure hunt hint, parse the image and respond **only** with JSON format, don't return the three quotes and JSON tag.
            In the list of hints ignore the question marks "?".
            Take care when reading coordinates, don't forget the - sign if there is one, and always double check your reading.
            The text "Départ [x, y]" is the starting position of the hunt.
            The description under it with "(xxxxx)" is the name of the map.
            You should only return the last hint line that you see in the list.
            Analyse all the arrows on the left of the hint list, and return for the last hint the direction of the arrow in this format: Number only, the direction of the last hint should be one of the following: 0 when the arrow is facing East (Right), 2 when the arrow is facing South (Down), 4 when the arrow is facing West (Left), 6 when the arrow is facing North (Up).
            If you see multiple hints in the dofus hunt list, only return the last one that has a white location pin on the right."""

        getPlayerPosPrompt = """[Roles: Dofus Expert]
            When presented with an image containing a Dofus player coordinates, parse the image and respond **only** with JSON.
            If you don't receive an image corresponding to a Dofus coordinates, please return an empty object `{}`.
            Do not include any extra text, explanations, or code fences. The JSON must have these keys:

            - `"playerPos"`: an array with the x and y coordinates (e.g., `[-16, 1]`).

            Example output with no extra verbiage or code fences:
            ```json
            {
            "playerPos": [-16, 2]
            }
            ```
            Focus on providing valid JSON only, with no accompanying statements."""

        class ReadHint(BaseModel):
            startPos: list[int, int]
            startPosDescription: str
            hintDirection: int
            hintText: str
            step: int
            totalSteps: int
            # isFirstHint: bool

        class ReadPlayerPos(BaseModel):
            playerPos: list[int, int]

        client = OpenAI()

        promptContent = [
            {
                "type": "text",
                "text": getPlayerPosPrompt if getPlayerPos else gpt_prompt,
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img_type};base64,{img_b64_str}"},
            },
        ]
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.3,
            response_format=ReadPlayerPos if getPlayerPos else ReadHint,
            messages=[{"role": "user", "content": promptContent}],
        )
        decoded_hint = self.auto_detect_and_fix(response.choices[0].message.parsed)
        serialized_hint = decoded_hint.json()
        self.log_message(f"GPT Response: {serialized_hint}")
        return serialized_hint

    def input_dofus_hint(self, json_response):
        start_x, start_y = json_response["startPos"]

        hint_text = json_response["hints"][-1]["hintText"]
        direction_code = str(json_response["hints"][-1]["hintDirection"])
        driver = self.selenium_driver

        # Direction mapping
        # "0" -> East, "2" -> South, "4" -> West, "6" -> North
        direction_map = {
            "6": "huntupwards",  # Upwards
            "0": "huntright",  # Right
            "4": "huntleft",  # Left
            "2": "huntdownwards",  # Downwards
        }

        try:
            if self.is_first_hint is True:
                # Fill in the position fields for the first hint
                x_input = driver.find_element(By.ID, "huntposx")
                y_input = driver.find_element(By.ID, "huntposy")
                x_input.clear()
                x_input.send_keys(str(start_x))
                y_input.clear()
                y_input.send_keys(str(start_y))
                self.is_first_hint = False
            else:
                x_input = driver.find_element(By.ID, "huntposx")
                y_input = driver.find_element(By.ID, "huntposy")
                self.log_message(
                    f"Current pos : {x_input.get_attribute('value')}, {y_input.get_attribute('value')}."
                )

            # Click the direction button
            direction_id = direction_map[str(direction_code)]
            driver.execute_script(f"document.querySelector('#{direction_id}').click();")

            # Normalize the hint_text (remove extra spaces, case insensitive)
            normalized_hint_text = re.sub(r"\s+", " ", hint_text.strip().lower())

            # Find the <select> element
            select_element = driver.find_element(By.ID, "clue-choice-select")
            select_object = Select(select_element)

            # Iterate through options and find the closest match
            enabled_options = [
                option
                for option in select_object.options
                if not option.get_attribute("disabled")
            ]
            for option in enabled_options:
                option_text = re.sub(r"\s+", " ", option.text.strip().lower())
                # self.log_message(f"Comparing hint: {option_text}")

                # Calculate similarity score using fuzzy matching
                similarity_score = fuzz.ratio(normalized_hint_text, option_text)

                if similarity_score >= 85:  # Adjust the threshold as needed
                    select_object.select_by_visible_text(option.text)
                    self.log_message(
                        f"Selected hint: {option.text} (Similarity: {similarity_score}%)",
                        "green",
                    )
                    break
            else:
                self.log_message("No matching hint found.", "red")
                return None

            form = driver.find_element(By.ID, "hunt-solver-data")
            form.submit()

            # Check for the result position
            # self.log_message("Checking for hint clue result...")
            result_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//div[@class='hunt-clue-result-position' and @id='hunt-clue-travel']",
                    )
                )
            )
            # Extract the data-travel attribute
            return result_element.get_attribute("data-travel")
        except Exception as e:
            self.log_message(f"Error while inputting hint: {e}", "red")
            return None

    def input_travel_command(self, travel_cmd):
        chat_region = self.config_data["chat_region"]
        random_x = chat_region["x"] + random.randint(0, chat_region["width"])
        random_y = chat_region["y"] + random.randint(0, chat_region["height"])
        pyautogui.click(random_x, random_y)
        pyautogui.typewrite(travel_cmd)
        send_keys("{ENTER}")
        self.play_with_volume("./assets/ping.mp3")

    def save_progression(self, hunt_name, data):
        try:
            # Ensure directory exists
            os.makedirs("progression_logs", exist_ok=True)

            # File path
            file_path = os.path.join("progression_logs", f"{hunt_name}.json")

            # Append new progression to JSON
            if os.path.exists(file_path):
                with open(file_path, "r") as file:
                    progression = json.load(file)
            else:
                progression = []

            progression.append(data)

            # Save updated progression
            with open(file_path, "w") as file:
                json.dump(progression, file, indent=4)

            self.log_message(f"Progression saved to {file_path}")
        except Exception as e:
            self.log_message(f"Failed to save progression: {e}", "red")

    def get_current_player_position(self):
        try:
            # Define the region for the player position coordinates
            player_region = self.config_data["player_region"]
            region_tuple = (
                player_region["x"],
                player_region["y"],
                player_region["width"],
                player_region["height"],
            )

            # Take a screenshot of the player position region
            screenshot = pyautogui.screenshot(region=region_tuple)
            screenshot.save("screenshot.png")

            # Send screenshot to GPT to retrieve the player position
            self.log_message("Sending player position to GPT...")
            response_data = self.send_to_chatgpt(screenshot, True)

            # Parse the position from the response
            data = json.loads(response_data)
            player_pos = data.get("playerPos")
            if player_pos and len(player_pos) == 2:
                return player_pos[0], player_pos[1]
            else:
                self.log_message(f"Invalid player position data: {data}", "red")
                raise ValueError(data)
        except Exception as e:
            self.log_message(f"Error retrieving player position: {e}", "red")
            return None, None


def main():
    app = DofusTreasureApp()
    app.mainloop()


if __name__ == "__main__":
    main()
