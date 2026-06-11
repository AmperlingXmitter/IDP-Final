"""
MobileNetV2-based classifier, sized for a Raspberry Pi 4 2GB.

Default: ImageNet base FROZEN + trainable head.  This is the cure for the
"only ~50% val accuracy" you saw: training the whole body at a high LR wipes
out the pretrained features (catastrophic forgetting). Keep the body frozen,
let the head learn, then optionally fine-tune the top layers at a LOW LR.
"""
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV2
import config as C


def build_model(n_classes, finetune=False, finetune_layers=30, imagenet=True):
    base = MobileNetV2(
        input_shape=(C.IMG_SIZE, C.IMG_SIZE, 3),
        alpha=C.ALPHA,
        include_top=False,
        weights="imagenet" if imagenet else None,   # None when we'll load our own weights
    )
    base.trainable = finetune
    if finetune:
        # unfreeze only the top N layers; keep BatchNorm layers frozen for stability
        for layer in base.layers[:-finetune_layers]:
            layer.trainable = False
        for layer in base.layers:
            if isinstance(layer, layers.BatchNormalization):
                layer.trainable = False

    inputs = tf.keras.Input(shape=(C.IMG_SIZE, C.IMG_SIZE, 3))
    x = base(inputs, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    x = layers.Dense(128, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(n_classes, activation="softmax")(x)

    model = models.Model(inputs, outputs)
    lr = C.FINETUNE_LR if finetune else C.LR
    model.compile(
        optimizer=tf.keras.optimizers.Adam(lr),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def enable_finetune(model, finetune_layers=40, lr=C.FINETUNE_LR):
    """Unfreeze the TOP layers of an ALREADY-TRAINED model and recompile at a
    LOW learning rate. This is the correct way to break past a frozen-base
    plateau without the catastrophic forgetting you saw with high-LR full
    fine-tuning. BatchNorm layers stay frozen for stability."""
    base = next((l for l in model.layers if isinstance(l, tf.keras.Model)), None)
    if base is None:
        raise ValueError("No backbone sub-model found to fine-tune.")
    base.trainable = True
    for layer in base.layers[:-finetune_layers]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, layers.BatchNormalization):
            layer.trainable = False
    model.compile(
        optimizer=tf.keras.optimizers.Adam(lr),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    n_trainable = sum(l.trainable for l in base.layers)
    print(f"[finetune] unfroze top {n_trainable} backbone layers at LR={lr}")
    return model
