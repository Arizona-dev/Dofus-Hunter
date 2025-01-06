import matplotlib.pyplot as plt
import pickle


def plot_training_history(history_file):
    with open(history_file, "rb") as f:
        history = pickle.load(f)

    # Plot Accuracy
    plt.plot(history["accuracy"], label="Train Accuracy")
    plt.plot(history["val_accuracy"], label="Validation Accuracy")
    plt.title("Model Accuracy")
    plt.xlabel("Epoch")
    plt.ylabel("Accuracy")
    plt.legend()
    plt.show()

    # Plot Loss
    plt.plot(history["loss"], label="Train Loss")
    plt.plot(history["val_loss"], label="Validation Loss")
    plt.title("Model Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.legend()
    plt.show()


if __name__ == "__main__":
    plot_training_history("training_history.pkl")
