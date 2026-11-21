# Historial de versiones

Cada versión tiene una etiqueta de git con el mismo nombre. Para ver una: `git show v0.6.0`.

## Sin publicar · 21 de noviembre de 2026 · Servidor web ordenado
- `web/app.py` queda solo con las rutas. Lo demás se separa: `web/settings.py` (qué se enciende y los secretos), `web/session.py` (contraseña, cookie firmada y origen) y `web/socket_adapter.py` (el WebSocket con la forma que espera `NovaServer`).
- La sesión ahora es una clase, `SessionGuard`, que deriva la clave de firma una sola vez en vez de pasar los secretos a cada función.
- No cambia nada para quien la usa: misma contraseña, misma cookie y mismas rutas. Probado en local: login correcto e incorrecto, sesión, rechazo de otro origen y conexión del WebSocket.

## v0.22.0 · 20 de noviembre de 2026 · Nova en la web
- Nova está al tanto de mi entorno. Mira por su cuenta cuando oye una voz que no es la mía, cuando oye un ruido raro y cada 20 minutos con el micrófono encendido.
- También decide sola cuándo mirar en la plática: si digo que no me siento bien con cómo me veo, si sueno mal, o si menciono a alguien que está conmigo. La cámara ya no espera a que diga "mira".
- Los ruidos los reconoce CED-tiny (AudioSet, 527 sonidos) en la Mac, cada segundo y en unos 3 ms. Alertan: golpes, vidrios, choques, gritos, llanto, alarmas, sirenas, ladridos, la puerta y el timbre. Mientras Nova habla no escucha, para no oírse a sí misma.
- Cada vistazo lo interpreta Haiku. Solo habla si importa: si me ve mal, oye algo roto, hay una emergencia o llegó alguien. Lo que vio queda como contexto unas horas, solo en memoria.
- Siempre hace la animación de foto al mirar, aunque la cámara ya esté prendida. Esas fotos no se guardan ni aparecen en el chat.
- Límites: un vistazo por minuto como máximo, uno cada 10 minutos por otra voz y uno cada 3 por ruido. Se reservan 10 fotos al día para cuando yo las pida; el límite diario sube a 60.
- `NOVA_GLANCE_MINUTES` cambia la rutina (0 la apaga) y `NOVA_AMBIENT_CAMERA=false` apaga todo esto. Nuevo `scripts/download_sound_model.py`.
- Nova manda reportes por correo: investigaciones, notas, resúmenes de lo que platicamos, planes y diagramas. Se le pide con la voz o escribiendo ("mándame por correo...").
- Los escribe Claude Sonnet 5.5 en segundo plano, con búsqueda web y lectura de páginas; la plática sigue con Haiku. Si Sonnet declina, la API reintenta con otro modelo (`fallbacks: "default"`).
- Los diagramas Mermaid se dibujan como imagen dentro de la Mac (`tools/mermaid`, mermaid-cli 12.2.0). Si uno no compila, Haiku lo corrige una vez; si aun así falla, va como texto.
- El correo sale por el SMTP de Gmail con una contraseña de aplicación (`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`). Lleva HTML con los diagramas, texto plano y el reporte en Markdown adjunto.
- El destinatario sale de la configuración, nunca del modelo: una página o un mensaje no pueden hacer que Nova le escriba a otra persona.
- La vista de gastos separa los reportes, con su propio color, y cobra cada llamada con el precio de su modelo.
- En la Mac, Nova reconoce mi voz. Se le enseña diciendo "Nova, apréndete mi voz" y luego unas frases; no pasa por Claude, y lo que digo para enseñarle no se guarda.
- Cada petición por voz se compara con mi huella (WeSpeaker ResNet34 vía sherpa-onnx, en la Mac). Si no soy yo, Nova responde, pero sin tratar a esa persona como si fuera yo ni contarle lo mío.
- Umbral de 0.6: con voces sintéticas, la misma voz dio 0.88 a 0.96 y otras voces 0.38 a 0.76. Cada petición registra su parecido para ajustarlo con voces reales.
- Corregido: "Aprenete mi voz", como lo escribió Whisper, no la ponía a aprender. Ahora acepta las variantes del verbo, pero no preguntas como "¿ya aprendiste mi voz?".
- Nova ya no repite una preocupación o un consejo que ya dio, ni insiste en que coma o descanse si no lo menciono. Tampoco condiciona lo que pido a eso: había respondido "primero come algo, luego te veo al equipo".
- Por voz, Nova solo me responde a mí. Lo que diga otra persona se ignora: ni se muestra, ni gasta un turno, ni llega a Claude. Escribiendo en el chat no cambia nada.
- Una frase muy corta para reconocerme ("sí", "va") vale si me reconoció en los últimos dos minutos. Al decir solo "Nova", saluda a cualquiera; la petición siguiente ya se revisa.
- La comparación quita los silencios antes y después de hablar. Con eso el umbral baja a 0.5: con mi voz real había dado 0.63 y 0.71, muy cerca de 0.6, y con el filtro me habría ignorado seguido.
- Corregido: con el micrófono real me ignoró. El recorte de silencios se medía contra el pico de la frase y dejaba menos de 0.8 s de voz. Ahora se mide contra el ruido del cuarto, y si queda poco se compara el audio completo. Cada comprobación registra cuántos segundos de voz usó.
- "Olvida mi voz" borra la huella. Nuevo `scripts/download_voice_model.py`, que comprueba la huella del modelo.
- Nova también corre en Vercel: `web/app.py` usa el mismo `NovaServer` y el mismo WebSocket que la Mac, con FastAPI.
- La web pide una contraseña. El navegador recibe una cookie firmada que no contiene ningún secreto, y el WebSocket solo acepta conexiones de la propia página.
- En la web no hay micrófono del servidor, escritorio, caras ni búsqueda por significado. Se oye con el dictado del navegador, y la interfaz oculta lo que no aplica.
- La memoria en la web se baja de Turso al conectarse y se sube al terminar cada turno.
- `server.py` carga Vosk, Whisper, InsightFace, Qdrant y CoreGraphics solo si los usa. La Mac funciona igual que antes.
- Nuevos `pyproject.toml`, `vercel.json` y `.vercelignore`. Nada de `.env` ni de `data/` se sube a Vercel.
- Nuevo documento `docs/Funcionamiento de Nova.md`: qué herramientas usa Nova, para qué sirve cada una, los mensajes del WebSocket, el recorrido de un turno por voz, la memoria y qué sale de la Mac.

## v0.21.6 · 8 de noviembre de 2026 · Voz nueva
- La voz de Nova pasa a Betty: juvenil y de caricatura. La anterior sonaba demasiado sensual.
- Habla más pareja y con menos estilo (estabilidad 0.6, estilo 0.1).
- Las otras voces que se probaron, entre ellas una robótica, quedan anotadas en `tts_service.py` para cambiar con `ELEVENLABS_VOICE_ID`.
- Los saludos guardados se generan de nuevo con la voz nueva.

## v0.21.5 · 7 de noviembre de 2026 · Menos platicadora
- Respuestas de una o dos frases, sin consejos extra, sin ofrecer más ayuda y sin preguntar al final si no hace falta.
- Solo se extiende si pido una explicación, pasos, un plan o código.
- Recibe los últimos 24 mensajes en vez de 40: cada llamada cuesta menos, y lo de antes sigue en su memoria.

## v0.21.4 · 7 de noviembre de 2026 · Sin mi nombre a cada rato
- Mi nombre como muletilla ("Ay, Carlos", "Gracias, Carlos", "Carlos, mira") se quita en el código: ni se oye ni se ve. En mi plática real aparecía en 18 de las últimas 30 respuestas.
- Las respuestas viejas se le muestran sin esos vocativos, para que deje de imitarlos.
- El saludo ya no dice mi nombre: "Hola, ¿cómo te puedo ayudar?".

## v0.21.3 · 7 de noviembre de 2026 · Se ve sobre la pantalla completa
- Corregido desde la v0.20.4: con otra app en pantalla completa, Nova se movía y hablaba, pero macOS no la dibujaba.
- Si macOS la deja amarrada a un escritorio, se vuelve a pedir que se vea en todos antes de aparecer. Cada aparición queda anotada en `data/desktop-window.log`.

## v0.21.2 · 7 de noviembre de 2026 · Whisper más fuerte
- Whisper pasa de `base` a `small` (488 MB): en una prueba con voces y ruido entendió 51 de 84 órdenes, contra 43 de `base`.
- Cada transcripción tarda unos 120 ms más. Si `small` no está descargado, se usa `base`.
- "Mira" ya no va en las frases de ejemplo para Whisper: una vez lo inventó y habría encendido la cámara.
- "Esto es todo" también cuenta como despedida.

## v0.21.1 · 7 de noviembre de 2026 · Entiende "ya vete"
- Corregido: Whisper confundía las órdenes cortas ("Beté", "Ya metes", "muévete" salía "muy bien"). Ahora se le dan de ejemplo.
- La despedida se reconoce sin acentos y en cualquier parte de una frase corta, como "ya olviden, ya vete". Una pregunta nunca cuenta como despedida.

## v0.21.0 · 7 de noviembre de 2026 · Directa, con despedida y saludos variados
- Respuestas más directas y simples: contesta en la primera frase, sin metáforas ni sermones.
- Si me despido ("adiós", "ya vete", "es todo", "buenas noches"), se despide en una línea, se oculta y deja de escuchar la plática hasta que la vuelva a llamar.
- El saludo cambia: "¿Qué pasó?", "Hola, ¿qué tal?", "Aquí estoy", "Te escucho", "Dime"… Nunca repite el mismo dos veces seguidas, y cada audio se genera una sola vez.

## v0.20.5 · 7 de noviembre de 2026 · Plática más humana
- Nova ya casi no dice mi nombre: solo en un momento serio o tierno.
- Menos muletillas al empezar, como "Ay" o "Qué gusto", y a lo mucho una etiqueta de voz por respuesta, solo si es real.
- Ya no menciona el día ni la hora si no viene al caso, ni repite el mismo consejo en cada respuesta.
- En una plática de prueba de 20 respuestas, mi nombre bajó de 16 a 0 y las etiquetas de voz de 20 a 2.

## v0.20.4 · 6 de noviembre de 2026 · Aparece al despertar la Mac
- Corregido: tras dormir la Mac, Nova oía y respondía, pero su ventana ya no aparecía.
- Al mostrarse reafirma su nivel y su posición; también al despertar, al desbloquear o al cambiar de monitor.
- Se reanuda el audio si quedó en pausa después de dormir.

## v0.20.3 · 6 de noviembre de 2026 · Sin apagarla por accidente
- Se quitó el botón de micrófono de la ventana flotante: quedaba junto a "Parar" y se podía apagar sin querer, y entonces Nova ya no oía a nadie.
- El micrófono ahora se controla desde el icono de la barra de menú.
- Si queda apagado, Nova aparece unos segundos para avisarlo, y al reabrir la app se vuelve a encender.

## v0.20.2 · 6 de noviembre de 2026 · Mira de verdad
- Corregido: con "Mira." o "Nova, mira" a veces contestaba sin ver, y al presentarle a alguien saludaba sin mirar. Ahora esas frases toman la foto directamente.
- Al presentarle a alguien saluda por el nombre que le diste, y pregunta si no sabe quién es quién.
- Esas fotos no esperan los 10 segundos entre una y otra, y no cuentan como cómo te ves tú.

## v0.20.1 · 6 de noviembre de 2026 · Ya no se queda muda
- Corregido: si el micrófono ya estaba encendido al abrir la app, Nova oía y respondía, pero sin sonido.

## v0.20.0 · 6 de noviembre de 2026 · Te reconoce
- Dile "Nova, apréndete mi cara": toma tres fotos y desde entonces te reconoce en las fotos que le pides.
- Corre en la Mac con `buffalo_sc` de InsightFace; la huella queda en un archivo local y no se sube a la nube.
- Si conoce tu cara, la memoria visual solo guarda fotos donde estás tú solo.
- Las caras de otras personas se comparan y se descartan: no se guarda nada de ellas.
- Se borra desde "Cómo te ve" o diciendo "olvida mi cara".
- Instalación: `.venv/bin/python scripts/download_face_model.py`. El modelo es solo para uso no comercial.

## v0.19.0 · 6 de noviembre de 2026 · Memoria visual
- Al pedirle que te vea, Nova anota prenda, color, gorra, lentes, cabello y vello facial; la foto no se guarda.
- Las costumbres se calculan contando, a partir de 5 fotos, y lo reciente pesa más.
- No hay ningún campo para cuerpo, peso, piel, edad, salud o ánimo, y si sale otra persona no se guarda nada.
- Vista "Cómo te ve" para revisarlo y borrarlo, y también se puede borrar pidiéndoselo.
- Falta probarlo con fotos reales: las pruebas usaron imágenes generadas.

## v0.18.0 · 6 de noviembre de 2026 · Mira cuando se lo pides
- Nova vuelve a poder ver desde la ventana flotante: si le pides que mire, la cámara se enciende para una sola foto y se apaga.
- Un punto rojo avisa mientras la cámara está encendida, y solo se le ofrece la foto si lo pides en ese mensaje.
- Si en una foto hay otra persona, no adivina quién es por su cara: pregunta.
- Corregido: una ventana sin turno en curso podía abrir el micrófono mientras Nova hablaba en otra.

## v0.17.0 · 6 de noviembre de 2026 · Se marea
- Si la tomas y la sacudes, se marea: ojos en espiral, estrellitas alrededor de la cabeza, y se tambalea unos segundos.

## v0.16.1 · 6 de noviembre de 2026 · Se le ve la mano
- Corregido: al saludar, la mano quedaba detrás del casco y parecía que se rascaba la cabeza.

## v0.16.0 · 6 de noviembre de 2026 · Te saluda
- Si la llamas sin pedir nada, aparece, alza la mano y dice "Hola Carlos, ¿cómo te puedo ayudar?", y luego te sigue escuchando.
- El saludo no pasa por el modelo y su audio se genera una sola vez: es inmediato y solo gasta créditos la primera vez.
- Mientras te atiende se queda quieta y de frente; solo se va a pasear unos segundos después.

## v0.15.0 · 6 de noviembre de 2026 · Nova, igual a su hoja
- Se redibujó a Nova con las medidas y la paleta de la hoja del personaje, en sus tres vistas.
- Llamas nuevas: lenguas onduladas que rematan en gancho, juntas en una sola masa, con brillos sueltos.
- Cuerpo más ancho, brazos más gorditos y largos, cabeza y visor más anchos, N más gruesa y cola en punta.
- Se le puede pedir que baile; también sigue bailando sola si algo la emociona mucho.

## v0.14.2 · 6 de noviembre de 2026 · Fiel a la hoja del personaje
- De espaldas, el fuego cubre toda la nuca, como en la referencia; ya no se ve el casco ni las costuras que se habían inventado.
- De perfil: visor más grande, un solo ojo, sin gema, con la bisagra del casco y un solo brazo que cuelga hacia atrás.
- La cola se curva más hacia atrás y las llamas se recargan hacia la nuca.

## v0.14.1 · 6 de noviembre de 2026 · Llamas de perfil
- Corregido: al voltear, las llamas se quedaban abiertas de frente. Ahora giran con la cabeza y forman un abanico de la coronilla a la nuca.
- Corregido: de perfil, la gema flotaba fuera del casco y la cara quedaba demasiado angosta.

## v0.14.0 · 6 de noviembre de 2026 · La vuelta completa y el baile
- Nova tiene vista de espaldas.
- Al volar hacia arriba se ve de espaldas, porque se aleja; en diagonal se ve de tres cuartos.
- Se le puede pedir que dé una vuelta o que enseñe la espalda; a veces da una vuelta sola al llegar.
- Baila si algo la pone muy feliz o la sorprende de golpe: brinca, se mece, alza los brazos, da una vuelta y suelta notas.
- Se quitaron el audífono y la aleta de la v0.13.0, que parecían antenas. La gema ya no se vuelve una punta delgada de perfil.

## v0.13.0 · 6 de noviembre de 2026 · Nova voltea
- Mira a dónde va: primero voltea hacia allá, luego arranca poco a poco y frena al llegar.
- Se ve casi de perfil al moverse a un lado: la cara se recorre, el cuerpo la sigue y el ojo lejano se oculta.
- Partes nuevas: audífono con aleta en la nuca, brazo del otro lado en sombra y pecho de perfil.
- Al volar lleva los brazos al frente, las llamas se van con el viento y la cola se curva hacia atrás.
- Parpadea al cambiar de lado, y se gira un poco cuando solo está mirando algo.
- De frente se ve igual que antes; con la compu abierta deja de pasear y se queda de frente.

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
