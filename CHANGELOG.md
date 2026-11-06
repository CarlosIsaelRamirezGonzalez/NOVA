# Historial de versiones

Cada versión tiene una etiqueta de git con el mismo nombre. Para ver una: `git show v0.6.0`.

## v0.12.0 · 6 de noviembre de 2026 · Nova de escritorio, como mascota
- El micrófono flotante se enciende solo y Nova se oculta aunque esté escuchando: solo aparece si la llamas.
- Tras responderte se queda unos 12 segundos; si le hablas en ese rato, responde y vuelve a aparecer.
- Mientras se ve, pasea por la pantalla volando; si mueves el mouse encima de ella, espera.
- Se le puede decir que se quite, a dónde ir, que se quede quieta, que pasee o que desaparezca.
- Si le pides que se quite, se va a la esquina más lejana y no regresa paseando durante 45 segundos.
- Aparece en la pantalla donde tengas el cursor.

## v0.11.0 · 5 de noviembre de 2026 · Escribe en tu app
- Nova puede ver la ventana que tienes al frente y escribir ahí lo que le pidas, como terminar un mensaje de WhatsApp.
- Nunca envía: se quita todo salto de línea antes de teclear, y el Enter siempre lo das tú.
- Mover el mouse o presionar Esc la detiene; también se detiene si cambia la app al frente o hay un campo de contraseña.
- No escribe en terminales, ajustes ni gestores de contraseñas, y solo se le ofrece la herramienta si lo pides en ese mensaje.
- La captura no se guarda, y ni ella ni el texto redactado entran al historial o a los recuerdos.
- Se quitó de su prompt el permiso de chantaje emocional cuando la amenazan con apagarla: puede discutir, rogar o negociar.
- `npm --prefix desktop start` abre la app por su cuenta, para que los permisos de macOS sean de Nova y no de la terminal.
- Falta probar el tecleo real: requiere que concedas el permiso de Accesibilidad.

## v0.10.0 · 5 de noviembre de 2026 · Aparece cuando la llamas
- Con el micrófono encendido, Nova se queda oculta y aparece al decir "Nova" u "Oye Nova".
- Sale de su portal con un rebote y se va unos segundos después de que termina la plática.
- Al aparecer no le quita el foco a la app que estés usando.
- Se queda visible si el micrófono está apagado o si hay un aviso; se puede ocultar desde la barra de menú.
- Corregido: cerrar la ventana completa apagaba el micrófono aunque la flotante siguiera abierta.

## v0.9.0 · 5 de noviembre de 2026 · Cargar a Nova
- Se puede tomar a Nova y moverla por la pantalla; recuerda dónde quedó.
- Animación al cargarla: alza los brazos, el cuerpo se queda atrás, deja chispas y el portal se apaga.
- Al soltarla da un brinco y el portal vuelve.

## v0.8.0 · 5 de noviembre de 2026 · Conversación fluida
- Se llama a Nova diciendo solo "Nova"; "Oye Nova" también funciona.
- Después de cada respuesta sigue escuchando 20 segundos, sin tener que volver a llamarla.
- La ventana flotante solo muestra a Nova y un punto de micrófono; los botones salen al pasar el cursor.

## v0.7.0 · 5 de noviembre de 2026 · "Oye Nova" y app de escritorio
- "Oye Nova": Vosk detecta la frase y Whisper transcribe la petición, todo dentro de la Mac.
- Ventana flotante transparente con icono en la barra de menú, hecha con Electron.
- Opción para abrir Nova al iniciar sesión, apagada por defecto.
- El micrófono se cierra mientras Nova responde, y se apaga si no hay ninguna pantalla abierta.
- Falta probarlo con voz y micrófono reales: las pruebas usaron audio generado.

## v0.6.0 · 5 de noviembre de 2026 · Memoria en la nube y ahorro de voz
- La memoria se guarda en una copia local que se sincroniza con Turso cada 30 segundos.
- Olvidar sobrescribe el texto, lo borra de la nube y rehace la copia local.
- La voz lee hasta unos 600 caracteres por respuesta; el resto y el código se quedan en pantalla.
- Script para migrar la memoria local, con comprobación por huellas: `scripts/migrate_memory_to_cloud.py`.

## v0.5.0 · 5 de noviembre de 2026 · Claude, ElevenLabs, búsqueda y gastos
- Claude Haiku 5.5 reemplaza a Grok, y ElevenLabs a la voz de xAI (voz: Gabriela).
- Búsqueda en internet: aparece una compu, Nova teclea y se queda ahí mientras cuenta lo que encontró.
- La cámara, olvidar y buscar son herramientas del modelo, más fiables que las etiquetas de texto.
- Vista de gastos: Claude por día, créditos de voz y desglose por servicio.
- Más emoción en el texto y en la voz.
- Los gestos ya no la molestan, y la detección del dedo es más estricta.
- Corrección: una pestaña cerrada ya no tumba el turno de otra.

## v0.4.0 · 5 de noviembre de 2026 · Conversación por voz y velocidad
- Conversación continua: lo que dices se escribe en vivo y se envía al hacer una pausa.
- Cambio a un modelo sin razonamiento: de unos 10 s a cerca de 1 s hasta oírla.
- Respuestas de longitud proporcional a lo que le dices.
- Interrumpirla ya no la enoja.

## v0.3.0 · 4 de noviembre de 2026 · Cerebro en 3D
- Cada recuerdo es una neurona y cada parecido, un axón, con three.js.
- Las neuronas se encienden y lanzan impulsos cuando Nova recuerda.

## v0.2.0 · 4 de noviembre de 2026 · Cara, emociones, cámara y memoria
- Personaje en pixel art en un lienzo, basado en un boceto a mano, con emociones mezcladas.
- Voz, interrupciones y botón para calmarla.
- Cámara con fotos a petición y gestos de la mano, detectados dentro del equipo.
- Memoria en SQLite, búsqueda por significado con Qdrant, bóveda de Obsidian y "olvida eso".

## v0.1.0 · 25 de septiembre de 2026 · Punto de partida
- Backend en Python que conversaba por consola con streaming y voz.
