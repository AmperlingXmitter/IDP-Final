"""
Lightweight U-Net for wound segmentation (separate model, trained on FUSeg).
Small enough for a Raspberry Pi 4. Loss/metric are registered as serializable
so the native .keras file reloads without passing custom_objects.
"""
import tensorflow as tf
from tensorflow.keras import layers, Model
import config as C


@tf.keras.utils.register_keras_serializable()
def dice_coef(y_true, y_pred, smooth=1.0):
    yt = tf.reshape(tf.cast(y_true, tf.float32), [-1])
    yp = tf.reshape(tf.cast(y_pred, tf.float32), [-1])
    inter = tf.reduce_sum(yt * yp)
    return (2.0 * inter + smooth) / (tf.reduce_sum(yt) + tf.reduce_sum(yp) + smooth)


@tf.keras.utils.register_keras_serializable()
def bce_dice_loss(y_true, y_pred):
    bce = tf.reduce_mean(tf.keras.losses.binary_crossentropy(y_true, y_pred))
    return bce + (1.0 - dice_coef(y_true, y_pred))


def _block(x, f):
    x = layers.Conv2D(f, 3, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x); x = layers.Activation("relu")(x)
    x = layers.Conv2D(f, 3, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x); x = layers.Activation("relu")(x)
    return x


def build_unet(size=None, filters=(16, 32, 64, 128), bottleneck=256):
    size = size or C.SEG_IMG_SIZE
    inp = tf.keras.Input((size, size, 3))
    skips, x = [], inp
    for f in filters:                       # encoder
        x = _block(x, f); skips.append(x); x = layers.MaxPool2D()(x)
    x = _block(x, bottleneck)               # bottleneck
    for f, skip in zip(reversed(filters), reversed(skips)):   # decoder
        x = layers.UpSampling2D()(x)
        x = layers.Concatenate()([x, skip])
        x = _block(x, f)
    out = layers.Conv2D(1, 1, activation="sigmoid")(x)
    model = Model(inp, out, name="wound_unet")
    model.compile(optimizer=tf.keras.optimizers.Adam(C.SEG_LR),
                  loss=bce_dice_loss, metrics=[dice_coef])
    return model
