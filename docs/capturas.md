# Capturas para el README

Lista para grabar las imágenes que faltan en el README. Guárdalas en `docs/assets/` con estos nombres
y reemplaza los comentarios `TODO` del README por la imagen.

## Cómo grabar

- **GIF o video corto:** `Cmd + Shift + 5` → "Grabar porción seleccionada". Recorta a 10–15 s.
- **Convertir a GIF** (opcional, con ffmpeg):
  `ffmpeg -i video.mov -vf "fps=15,scale=900:-1:flags=lanczos" -loop 0 docs/assets/nombre.gif`
- Antes de grabar: cierra notificaciones y ventanas con datos personales, y usa una conversación de
  prueba. Nada de claves, correos ni nombres reales en pantalla.

## Lista

| Archivo | Qué mostrar | Dónde va |
|---|---|---|
| `docs/assets/oye-nova.gif` | Escritorio vacío, decir "Oye Nova", que salga del portal, salude y responda | Arriba, bajo la hoja del personaje |
| `docs/assets/emociones.gif` | Darle una noticia triste y luego una buena: el cuerpo cambia de emoción | "Qué hace" |
| `docs/assets/cerebro.png` | La vista de memoria en 3D con neuronas encendidas | "Qué hace" |
| `docs/assets/escritura.gif` | Pedirle que termine un mensaje de prueba y verla teclear sin enviar | "Privacidad y seguridad" |
| `docs/assets/gastos.png` | La vista de gastos del día | "Qué hace" |
| `docs/assets/baile.gif` | Darle una gran noticia para que baile, o sacudirla para que se maree | "Qué hace" |

La bitácora (`docs/desarrollo-de-nova.md`, columna "Qué mostrar") tiene una escena para cada capítulo,
por si quieres más.
