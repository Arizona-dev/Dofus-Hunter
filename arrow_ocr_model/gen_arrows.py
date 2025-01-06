import os
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.utils import img_to_array, load_img

# Define the data augmentation parameters
datagen = ImageDataGenerator(
    rescale=1.0 / 255.0,  # Normalize pixel values to [0, 1]
    rotation_range=0,  # Allow slight rotation
    brightness_range=[0.9, 1.1],  # Slightly adjust brightness
    width_shift_range=0,  # Small horizontal shifts
    height_shift_range=0,  # Small vertical shifts
    zoom_range=0.1,  # Small zoom
)

# Define input and output directories
base_input_dir = "real"  # Original dataset directory
base_output_dir = "augmented"  # Output directory for augmented images
directions = ["East", "West", "North", "South"]  # Subdirectories for directions
target_size = (64, 64)  # Target image size

# Ensure the output directories exist
os.makedirs(base_output_dir, exist_ok=True)
for direction in directions:
    os.makedirs(os.path.join(base_output_dir, direction), exist_ok=True)

# Generate 100 augmented images for each direction
for direction in directions:
    input_dir = os.path.join(base_input_dir, direction)
    output_dir = os.path.join(base_output_dir, direction)
    
    for filename in os.listdir(input_dir):
        if filename.endswith((".png", ".jpg", ".jpeg")):  # Only process image files
            img_path = os.path.join(input_dir, filename)
            img = load_img(img_path, target_size=target_size)  # Load and resize image
            img_array = img_to_array(img).reshape((1, *target_size, 3))  # Convert to array

            # Generate 100 augmented images
            count = 0
            for batch in datagen.flow(
                img_array,
                batch_size=1,
                save_to_dir=output_dir,
                save_prefix="aug",
                save_format="png",
            ):
                count += 1
                if count >= 100:
                    break
            print(f"Generated 100 augmented images for {direction}: {filename}")
