import tkinter as tk
from tkinter import scrolledtext, messagebox
import pyautogui
import threading
import json
import os
import re
import pyperclip
import random
import pygame
import time
import sqlite3
import numpy as np
import mouse
from pynput.keyboard import Key, Controller
from fuzzywuzzy import fuzz
from io import BytesIO
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pywinauto.keyboard import send_keys
from OCR.screenshot import (
    read_hunt_from_screenshot,
    process_coordinates_image,
)

load_dotenv()

CONFIG_FILE = "config.json"


class CoordinateHelper:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Coordinate Helper")
        self.coordinates = []
        self.waiting = False

    def on_click(self, event):
        if not self.waiting:
            self.coordinates.append((event.x, event.y))
            self.waiting = True
            print(
                f"Position {len(self.coordinates)} captured at ({event.x}, {event.y})"
            )
            print("Press Enter for next capture, or Escape to finish")

    def on_key(self, event):
        if event.keysym == "Return" and self.waiting:
            self.waiting = False
            print(f"Ready for position {len(self.coordinates) + 1}")
            print(
                f"Click position {len(self.coordinates) + 1} (Press Enter for next, Escape to finish)"
            )
        elif event.keysym == "Escape":
            if len(self.coordinates) > 0:
                self.root.quit()
            else:
                print("Cannot finish without at least one position captured")

    def update_label(self, text):
        self.label.config(text=text)

    def get_coordinates(self):
        self.root.bind("<Button-1>", self.on_click)
        self.root.bind("<Key>", self.on_key)
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-fullscreen", True)
        print("Starting coordinate capture")
        print("Click positions and press Enter after each click")
        print("Press Escape when finished")
        self.root.mainloop()
        self.root.destroy()
        return self.coordinates


def load_config(filename="config.json"):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Config file is missing.")


def save_config(config, filename="config.json"):
    with open(filename, "w") as f:
        json.dump(config, f, indent=2)


def setup_automation(self):
    """Interactive setup function to configure click positions"""
    print("Starting setup mode...")
    print("You will be asked to click 4 positions.")
    print("After each click, press any key to continue to next position.")

    # Get click coordinates
    helper = CoordinateHelper()
    coordinates = helper.get_coordinates()

    # Load existing config and add coordinates
    config = load_config()
    config["click_positions"] = [[x, y] for x, y in coordinates]

    # Save updated config
    save_config(config)

    print("\nSetup completed! Coordinates saved to config file:")
    for i, (x, y) in enumerate(coordinates, 1):
        print(f"Position {i}: ({x}, {y})")
    return coordinates


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
        self.current_hunt_id = None
        self.hintDirection = None
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

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

        # Label to display mouse position
        self.is_debugging = False
        self.position_label = tk.Label(
            self.main_frame, text="Mouse Position: (X, Y)", font=("Arial", 14)
        )
        self.toggle_button = tk.Button(
            self.main_frame, text="Start Debugging", command=self.toggle_debugging
        )

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

        self.new_hunt_button = tk.Button(
            self.main_frame,
            text="New Hunt",
            font=("Arial", 12, "bold"),
            bg="#5DA130",
            fg="white",
            command=self.new_hunt,
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
        self.initialize_database()

    def initialize_database(self):
        self.conn = sqlite3.connect(
            "progression.db", check_same_thread=False, timeout=10
        )
        self.cursor = self.conn.cursor()
        # Create the `hunt` table with fields for the new structure
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS hunt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_pos_zone TEXT,
                start_pos_x INTEGER,
                start_pos_y INTEGER,
                last_hint_pos_x INTEGER,
                last_hint_pos_y INTEGER,
                step INTEGER,
                total_steps INTEGER,
                hints TEXT,
                remaining_tries INTEGER,
                status TEXT CHECK(status IN ('current', 'cancelled', 'finished')) DEFAULT 'current',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.commit()

    def close_database(self):
        if self.conn:
            self.conn.close()

    def toggle_debugging(self):
        if self.is_debugging:
            self.is_debugging = False
            self.toggle_button.config(text="Start Debugging")
        else:
            self.is_debugging = True
            self.toggle_button.config(text="Stop Debugging")
            threading.Thread(target=self.update_mouse_position, daemon=True).start()

    def update_mouse_position(self):
        while self.is_debugging:
            # Get mouse position
            x, y = pyautogui.position()
            position_text = f"Mouse Position: ({x}, {y})"

            # Update the label
            self.position_label.config(text=position_text)

            # Update every 100 ms
            time.sleep(0.1)

    def place_widgets(self):
        # Heading Label
        self.heading_label.pack(fill=tk.X, pady=10)

        self.position_label.pack(pady=10)
        self.toggle_button.pack(pady=10)

        # Row for Start Hunt and Setup Buttons
        self.separator.pack(in_=self.button_row, fill=tk.X, pady=(0, 20))
        self.start_hunt_button.pack(in_=self.button_row, side=tk.LEFT, expand=tk.TRUE)
        self.new_hunt_button.pack(in_=self.button_row, side=tk.LEFT, expand=tk.TRUE)
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
        else:
            self.log_message("End hunt button not initialized.", "red")
        self.hunt_started = False
        self.last_travel_cmd = None
        self.is_first_hint = True
        self.hintDirection = None
        self.selenium_driver.refresh()
        # Change hunt status to completed
        if self.current_hunt_id:
            self.set_hunt_to_finished()
        self.log_message("Hunt ended.", "green")

    def move_mouse_and_click(self, target_x, target_y):
        steps_per_second = 160
        duration = 0.3
        start_x, start_y = mouse.get_position()
        steps = int(duration * steps_per_second)
        for step in range(1, steps + 1):
            # Calculate linear interpolation
            x = start_x + (target_x - start_x) * (step / steps)
            y = start_y + (target_y - start_y) * (step / steps)

            # Add small randomness to simulate human movement
            x += random.uniform(-3, 3)
            y += random.uniform(-3, 3)

            # Move the mouse to the new position
            mouse.move(x, y, absolute=True, duration=0)

            # Wait between steps
            time.sleep(1 / steps_per_second)
        time.sleep(random.uniform(0.1, 0.3))
        mouse.press(button="left")
        time.sleep(random.uniform(0.05, 0.08))
        mouse.release(button="left")

    def run_automation(self, delay_between_actions=3.2):
        """Run the automation with specified delays between actions"""
        config = load_config()
        if "click_positions" not in config:
            self.log_message("No coordinates found in config! Please run setup first.")
            return False

        coordinates = [(pos[0], pos[1]) for pos in config["click_positions"]]

        try:
            keyboard = Controller()
            self.log_message("Going to get a new hunt...")
            time.sleep(1)
            # Press initial key
            self.log_message("Pressing 'ç' to use recall potion...")
            # keyboard.press("ç")
            # time.sleep(0.05)
            # keyboard.release("ç")
            # time.sleep(delay_between_actions)

            # Type travel command
            self.log_message("Going to La malle au trésor...")
            self.input_travel_command("/travel -25,-36")
            send_keys("{ENTER}")
            time.sleep(5)

            # Perform clicks
            for i, (x, y) in enumerate(coordinates, 1):
                self.log_message(f"Clicking position {i}... {x, y}")
                self.move_mouse_and_click(x, y)
                time.sleep(delay_between_actions)

            self.log_message("Teleporting to zaap of hunt zone...")
            # Go to zaap map
            self.input_travel_command("/travel -27,-36")
            time.sleep(delay_between_actions * 4)
            # Click on zaap
            zaap_position = config.get("zaap_position")
            if zaap_position:
                self.move_mouse_and_click(*zaap_position)
            else:
                self.log_message(
                    "Zaap position is not defined in the configuration.", "red"
                )
            time.sleep(delay_between_actions)
            # Enter zaap name
            current_hunt_progression = self.get_last_progression()
            start_pos_zone = current_hunt_progression["start_pos_zone"]
            start_pos_zone = start_pos_zone.split("(")[0].strip()
            pyautogui.typewrite(start_pos_zone)
            send_keys("{ENTER}")

            # Go to start coordinates of the new hunt
            start_pos_x = current_hunt_progression["start_pos_x"]
            start_pos_y = current_hunt_progression["start_pos_y"]
            self.input_travel_command(f"/travel {start_pos_x},{start_pos_y}")

            # Wait for the player to reach the target position
            while True:
                current_position = self.get_current_player_position()

                # Check if the player has arrived
                if current_position == (start_pos_x, start_pos_y):
                    self.log_message(
                        "Player has successfully reached the start position."
                    )
                    break  # Exit the loop when the position matches

                # Log progress and wait before the next check
                self.log_message(
                    f"Waiting for player to arrive... Current position: {current_position}"
                )
                time.sleep(3)  # Adjust the interval as needed

            self.log_message("\nAutomation completed successfully!")

        except pyautogui.FailSafeException:
            self.log_message("Automation aborted by moving mouse to corner", "red")
        except Exception as e:
            self.log_message(f"An error occurred: {str(e)}", "red")

    def new_hunt(self):
        threading.Thread(target=self.run_automation, daemon=True).start()

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
        textColor = "black"
        if color:
            textColor = color

        self.log_display.tag_configure(tag_name, foreground=textColor)

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

                # Sending to OCR
                required_fields = [
                    "start_pos_zone",
                    "start_pos_x",
                    "start_pos_y",
                    "step",
                    "total_steps",
                    "remaining_tries",
                    "hints",
                    "last_hint_pos_x",
                    "last_hint_pos_y",
                ]
                self.log_message("Reading hints...")
                screenshot = pyautogui.screenshot(region=region_tuple)
                response_data = read_hunt_from_screenshot(screenshot)
                data = json.loads(response_data)
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
                    self.log_message("Error: No hints provided in response.", "red")
                    # self.next_hint()
                    self.start_hunt_button.config(state=tk.NORMAL)
                    return

                # Retrieve the last hint
                last_hint = data["hints"][-1]
                self.log_message(
                    f"Last hint: {json.dumps(data['hints'][-1], indent=2, ensure_ascii=False)}",
                    "blue",
                )

                # self.hintDirection = last_hint["hintDirection"]

                if "hintText" not in last_hint or "hintDirection" not in last_hint:
                    self.log_message(
                        "Error: Invalid hint structure in response. Retrying...", "red"
                    )
                    self.log_message(f"Received hints: {data['hints']}", "red")
                    # self.next_hint()
                    return

                # Save progression to JSON
                self.save_progression(data)
                # Set is_first_hint to False if it's not step 1 and if the hints array is not length one
                if data["step"] != 1 or len(data["hints"]) != 1:
                    self.is_first_hint = False

                if self.hintDirection is None:
                    # Validate hintDirection
                    valid_directions = {0, 2, 4, 6}
                    if last_hint["hintDirection"] not in valid_directions:
                        self.log_message(
                            f"Invalid hintDirection: {last_hint['hintDirection']}. Retrying...",
                            "red",
                        )
                        return

                # Input data into hint finder
                self.log_message("Searching hint...")
                travel_cmd = self.input_dofus_hint(data)
                if travel_cmd is None:
                    self.log_message(
                        "Hint not found, You can try again by clicking 'Next Hint'.",
                        "red",
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
                pyperclip.copy(travel_cmd)
                self.input_travel_command(travel_cmd)

                # Reset the UI
                self.start_hunt_button.config(state=tk.NORMAL)
                self.hintDirection = None
            except Exception as e:
                self.log_message(f"Error during hunt: {e}", "red")
                self.start_hunt_button.config(state=tk.NORMAL)

        threading.Thread(target=do_hunt).start()

    def input_dofus_hint(self, json_response):
        driver = self.selenium_driver
        current_hunt_progression = json_response
        start_x = json_response["start_pos_x"]
        start_y = json_response["start_pos_y"]

        hint_text = json_response["hints"][-1]["hintText"]
        direction_code = str(json_response["hints"][-1]["hintDirection"])

        # Direction mapping
        # "0" -> East, "2" -> South, "4" -> West, "6" -> North
        direction_map = {
            "6": "huntupwards",  # Upwards
            "0": "huntright",  # Right
            "4": "huntleft",  # Left
            "2": "huntdownwards",  # Downwards
        }

        try:
            # Check if it's the first step and hint, if yes, input the start position, else get the lastHintPosition from the progression logs
            x_input = driver.find_element(By.ID, "huntposx")
            y_input = driver.find_element(By.ID, "huntposy")
            if self.is_first_hint:
                print("Its first hint input")
                x_input.clear()
                x_input.send_keys(str(start_x))
                y_input.clear()
                y_input.send_keys(str(start_y))
                self.is_first_hint = False
            else:
                # Fill x, y inputs with current position if empty
                x = x_input.get_attribute("value")
                y = y_input.get_attribute("value")
                self.log_message("in else conditon")
                if int(x) == 0 and int(y) == 0:
                    print("Its first dofus db input")
                    current_hunt_progression = self.get_last_progression()
                    self.log_message(f"in {current_hunt_progression}")

                    if (
                        current_hunt_progression is None
                        or current_hunt_progression["last_hint_pos_x"] is None
                        or current_hunt_progression["last_hint_pos_y"] is None
                    ):
                        current_position = self.get_current_player_position()
                        self.log_message(f"Player pos: {current_position}")

                        if current_position:
                            x = current_position[0]
                            y = current_position[1]
                        else:
                            self.log_message("Error loading player pos.", "red")
                    else:

                        x = current_hunt_progression["last_hint_pos_x"]
                        y = current_hunt_progression["last_hint_pos_y"]
                        self.log_message(f"seems to have all: {x}, {y}")

                    self.log_message(f"Using pos: [{x}, {y}]")
                    x_input.clear()
                    x_input.send_keys(str(x))
                    y_input.clear()
                    y_input.send_keys(str(y))

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

                # Calculate similarity score using fuzzy matching
                similarity_score = self.compare_hint_texts(
                    normalized_hint_text, option_text
                )
                if (
                    similarity_score >= 95
                ):  # Using a higher threshold since we're checking word by word
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
            result_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//div[@class='hunt-clue-result-position' and @id='hunt-clue-travel']",
                    )
                )
            )

            x = x_input.get_attribute("value")
            y = y_input.get_attribute("value")
            current_hunt_progression["last_hint_pos_x"] = x
            current_hunt_progression["last_hint_pos_y"] = y
            self.save_progression(current_hunt_progression)

            # Extract the data-travel attribute
            return result_element.get_attribute("data-travel")
        except Exception as e:
            self.log_message(f"Error while searching hint: {e}", "red")
            return None

    def execute_with_retries(self, cursor, query, params, retries=5, delay=0.5):
        for attempt in range(retries):
            try:
                cursor.execute(query, params)
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    print(f"Database is locked. Retrying {attempt + 1}/{retries}...")
                    time.sleep(delay)
                else:
                    raise
        raise ValueError("Failed to execute query after multiple retries.")

    def save_progression(self, data):
        try:
            # Serialize hints into JSON
            hints_json = json.dumps(data.get("hints", []))
            current_hunt_id = data.get("id")

            # Retry logic for database access
            def execute_with_retries(query, params):
                self.execute_with_retries(self.cursor, query, params)

            if current_hunt_id is None:
                self.cursor.execute(
                    """
                    SELECT * FROM hunt
                    WHERE status = 'current'
                    """
                )
                current_hunt = self.cursor.fetchone()

                if current_hunt:
                    self.current_hunt_id = current_hunt[0]
                    execute_with_retries(
                        """
                        UPDATE hunt
                        SET 
                            start_pos_zone = ?,
                            start_pos_x = ?,
                            start_pos_y = ?,
                            last_hint_pos_x = ?,
                            last_hint_pos_y = ?,
                            step = ?,
                            total_steps = ?,
                            hints = ?,
                            remaining_tries = ?
                        WHERE id = ?
                        """,
                        (
                            data.get("start_pos_zone"),
                            data.get("start_pos_x"),
                            data.get("start_pos_y"),
                            data.get("last_hint_pos_x"),
                            data.get("last_hint_pos_y"),
                            data.get("step"),
                            data.get("total_steps"),
                            hints_json,
                            data.get("remaining_tries"),
                            current_hunt[0],
                        ),
                    )
                    current_hunt_id = current_hunt[0]
                else:
                    execute_with_retries(
                        """
                        INSERT INTO hunt (
                            start_pos_zone,
                            start_pos_x,
                            start_pos_y,
                            last_hint_pos_x,
                            last_hint_pos_y,
                            step,
                            total_steps,
                            hints,
                            remaining_tries,
                            status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            data.get("start_pos_zone"),
                            data.get("start_pos_x"),
                            data.get("start_pos_y"),
                            data.get("last_hint_pos_x"),
                            data.get("last_hint_pos_y"),
                            data.get("step"),
                            data.get("total_steps"),
                            hints_json,
                            data.get("remaining_tries"),
                            "current",
                        ),
                    )
                    self.current_hunt_id = self.cursor.lastrowid
            else:
                self.current_hunt_id = current_hunt_id
                execute_with_retries(
                    """
                    INSERT INTO hunt (
                        id, start_pos_zone, start_pos_x, start_pos_y,
                        last_hint_pos_x, last_hint_pos_y, step, total_steps, hints, remaining_tries
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        start_pos_zone = excluded.start_pos_zone,
                        start_pos_x = excluded.start_pos_x,
                        start_pos_y = excluded.start_pos_y,
                        last_hint_pos_x = excluded.last_hint_pos_x,
                        last_hint_pos_y = excluded.last_hint_pos_y,
                        step = excluded.step,
                        total_steps = excluded.total_steps,
                        hints = excluded.hints,
                        remaining_tries = excluded.remaining_tries
                    """,
                    (
                        current_hunt_id,
                        data.get("start_pos_zone"),
                        data.get("start_pos_x"),
                        data.get("start_pos_y"),
                        data.get("last_hint_pos_x"),
                        data.get("last_hint_pos_y"),
                        data.get("step"),
                        data.get("total_steps"),
                        hints_json,
                        data.get("remaining_tries"),
                    ),
                )

            self.conn.commit()
            self.log_message(f"Progression saved for id {self.current_hunt_id}.")

        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                raise ValueError("Database is locked. Please retry.")
            else:
                raise
        except Exception as e:
            raise ValueError(e)

    def get_last_progression(self):
        try:
            # Retrieve the most recent progression entry by timestamp
            self.cursor.execute(
                """
                SELECT start_pos_zone, start_pos_x, start_pos_y,
                    last_hint_pos_x, last_hint_pos_y, step, total_steps,
                    hints, remaining_tries, status, timestamp
                FROM hunt
                WHERE status = 'current'
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            result = self.cursor.fetchone()
            if result:
                # Ensure 'hints' is a valid JSON string before deserializing
                self.current_hunt_id = result[0]
                print(f"load last hunt {self.current_hunt_id}")

                hints_raw = result[8]
                try:
                    hints = (
                        json.loads(hints_raw)
                        if isinstance(hints_raw, (str, bytes, bytearray))
                        else []
                    )
                except json.JSONDecodeError:
                    # Handle invalid JSON data gracefully
                    self.log_message(
                        "Invalid JSON in 'hints' column; defaulting to empty list",
                        "orange",
                    )
                    hints = []

                return {
                    "start_pos_zone": result[0],
                    "start_pos_x": result[1],
                    "start_pos_y": result[2],
                    "last_hint_pos_x": result[3],
                    "last_hint_pos_y": result[4],
                    "step": result[5],
                    "total_steps": result[6],
                    "hints": hints,
                    "remaining_tries": result[7],
                    "timestamp": result[10],
                }
        except Exception as e:
            self.log_message(f"No hunt found: {e}", "orange")
            return None

    def set_hunt_to_finished(self):
        """
        Updates the status of the current hunt to 'finished' in the database.
        """
        if not self.current_hunt_id:
            raise ValueError("Current hunt ID is not set. Cannot update hunt status.")

        try:
            # Execute the update query
            self.cursor.execute(
                """
                UPDATE hunt
                SET status = ?
                WHERE id = ?
                """,
                ("finished", self.current_hunt_id),
            )
            self.connection.commit()  # Ensure the changes are saved to the database
            print(f"Hunt ID {self.current_hunt_id} set to 'finished'.")
        except Exception as e:
            # Log or raise an exception for debugging
            print(f"Error updating hunt status: {e}")
            raise

    def input_travel_command(self, travel_cmd):
        try:
            if "chat_region" not in self.config_data:
                raise ValueError("Chat region not set.")
            chat_region = self.config_data["chat_region"]
            random_x = chat_region["x"] + random.randint(0, chat_region["width"])
            random_y = chat_region["y"] + random.randint(0, chat_region["height"])
            self.move_mouse_and_click(random_x, random_y)
            # pyautogui.click(random_x, random_y)
            pyautogui.typewrite(travel_cmd)
            send_keys("{ENTER}")
            send_keys("{ENTER}")
            self.play_with_volume("./assets/ping.mp3")
        except Exception as e:
            self.log_message(f"Error while inputting travel command: {e}", "red")

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
            # Convert screenshot to numpy array
            screenshot_array = np.array(screenshot)

            # Process screenshot to get coordinates
            self.log_message("Reading player position...")
            response_data = process_coordinates_image(screenshot_array)

            # Check if coordinates were found
            if response_data["success"] and response_data["coordinates"]:
                # Get first coordinate pair
                position = response_data["coordinates"][0]
                return position["x"], position["y"]
            else:
                error_msg = response_data.get("error", "No coordinates found")
                raise ValueError(error_msg)

        except Exception as e:
            self.log_message(f"Error retrieving player position: {e}", "red")
            return None, None

    def compare_hint_texts(self, hint_text, option_text):
        # Split into words
        hint_words = hint_text.lower().split()
        option_words = option_text.lower().split()

        # If different number of words, they're not the same hint
        if len(hint_words) != len(option_words):
            return 0

        # Compare each word pair and get minimum similarity
        word_similarities = []
        for hint_word, option_word in zip(hint_words, option_words):
            word_similarity = fuzz.ratio(hint_word, option_word)
            word_similarities.append(word_similarity)

        # Return the minimum similarity found
        # This way, if any word pair has low similarity, the overall score will be low
        return min(word_similarities)


def main():
    app = DofusTreasureApp()
    app.mainloop()


if __name__ == "__main__":
    main()
