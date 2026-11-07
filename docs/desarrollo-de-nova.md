# Nova de 0 a 100: bitácora de desarrollo

Guía para contar cómo se construyó Nova. Las cifras se midieron durante el desarrollo, en pruebas
pequeñas; sirven para contar la historia, no como comparaciones formales.

## Qué es Nova
Una compañera de IA personal que vive en la computadora: conversa con voz en español de México,
siente emociones que se ven en su cuerpo, recuerda lo que le cuentas, mira por la cámara cuando se lo
pides y busca en internet.

## La historia por capítulos
Para volver a cualquier punto: `git checkout v0.3.0`. Las versiones anteriores usan otras APIs, así
que pueden requerir sus claves de entonces; para el video, conviene grabarlas también como capturas.

| Capítulo | Versión | Qué mostrar | El giro de la historia |
|---|---|---|---|
| 1. El origen | `v0.1.0` | Nova en la consola | Solo texto y voz: funciona, pero no se siente nadie ahí |
| 2. Darle cara | `v0.2.0` | El boceto en papel y el personaje en pixel art | Lottie y un robot no convencieron; el boceto a mano sí |
| 3. Darle sentimientos | `v0.2.0` | Emociones mezcladas y el botón Calmar | Al principio siempre estaba neutra; "feliz" parecía enamorada |
| 4. Personalidad | `v0.2.0` | Una discusión en la que opina y aun así ayuda | De asistente servil a alguien como Alfred con Bruce Wayne |
| 5. Que te vea | `v0.2.0` | Fotos a petición y gestos de la mano | Todo se detecta dentro del equipo; las fotos tienen límite |
| 6. Que te recuerde | `v0.2.0` | Le cuentas algo y lo recuerda después de reiniciar | SQLite, significado con Qdrant, emociones en cada recuerdo |
| 7. Ver su mente | `v0.3.0` | Neuronas en 3D que se encienden | Un grafo plano se convirtió en un cerebro |
| 8. Quitarle lo lento | `v0.4.0` | Antes y después: 10 s contra 1 s | El modelo "pensaba" antes de escribir la primera palabra |
| 9. Hablar de corrido | `v0.4.0` | Conversación sin tocar el teclado | Hablaba demasiado: tocó enseñarle a medirse |
| 10. Que investigue | `v0.5.0` | La compu y el tecleo | La compu se iba antes de que hablara; ahora se queda |
| 11. Cambiar de cerebro | `v0.5.0` | Misma frase con la voz nueva | Migrar expuso qué dependía del modelo anterior |
| 12. Cuentas claras | `v0.5.0` | La vista de gastos | Qué cuesta de verdad tener una IA personal |
| 13. Memoria en la nube | `v0.6.0` | La misma memoria comprobada en otra copia | "Olvidar" no borraba de verdad, y se corrigió |
| 14. Sale del navegador | `v0.7.0` | Nova flotando en el escritorio | La primera versión de la frase se activaba casi con cualquier cosa |
| 15. Llamarla por su nombre | `v0.7.0` | Decir "Oye Nova" desde otra app | Nada del audio sale de la Mac; solo viaja el texto |
| 16. Platicar de corrido | `v0.8.0` | Varias preguntas seguidas diciendo solo "Nova" una vez | Repetir la frase cada vez rompía la plática |
| 17. Cargarla con el cursor | `v0.9.0` | Arrastrarla por toda la pantalla | La forma nativa de mover ventanas no dejaba animar nada: hubo que hacerla a mano |
| 18. Aparece cuando la llamas | `v0.10.0` | El escritorio vacío, decir "Nova" y verla salir del portal | Oculta tenía que seguir oyendo: la ventana se esconde, pero nunca se apaga |
| 19. Manos en la compu | `v0.11.0` | Pedirle que termine un mensaje de prueba y verla teclear | Antes de darle manos se le quitó el chantaje, y el Enter se eliminó desde el código |
| 20. Una mascota en el escritorio | `v0.12.0` | Decirle "muévete, no me dejas ver" y verla volar a otra esquina | Ocultarla no era apagarla: tuvo que aparecer solo cuando se le llama |
| 21. Nova voltea | `v0.13.0` | Verla girar y volar de perfil de un lado a otro | Sin dibujar cada ángulo: la cabeza se calcula como algo redondo, y en la primera prueba el audífono parecía otro ojo |
| 22. La vuelta completa y el baile | `v0.14.2` | Comparar la hoja del personaje con Nova de perfil y de espaldas, y darle una gran noticia para que baile | Se dibujó sin revisar la hoja del personaje: las antenas y las costuras inventadas se quitaron |
| 23. Igual a su hoja | `v0.15.0` | La hoja del personaje junto a Nova redibujada, y luego bailando | Se midió la hoja en lugar de calcular a ojo: el mismo código ahora dibuja las tres vistas |
| 24. Te saluda | `v0.16.0` | Decir "Oye Nova" y que salga a saludar con la mano | Aparecer no bastaba: se iba volando sin decir nada. El saludo se guarda para no pagarlo cada vez |
| 25. Se marea | `v0.17.0` | Agarrarla, sacudirla y verla tambalearse con estrellitas | Se detecta contando cambios bruscos de dirección, para que moverla normal no la maree |
| 26. Mira cuando se lo pides | `v0.18.0` | Pedirle "mira esto" y ver el punto rojo prenderse solo esa vez | Flotar le había quitado la vista sin que nadie lo notara; volvió con la cámara apagada por defecto |
| 27. Memoria visual | `v0.19.0` | Pedirle "¿cómo vengo hoy?" varios días y abrir "Cómo te ve" | Qué se guarda se limitó con el esquema: lo que no tiene campo no se puede guardar |
| 28. Te reconoce | `v0.20.0` | Decirle "apréndete mi cara" y que distinga quién está en la foto | Solo aprende a una persona: la huella se queda en la Mac y las caras ajenas se descartan |
| 29. Saluda y se despide | `v0.21.0` | Llamarla varias veces, oír saludos distintos y despedirla con "ya es todo" | Despedirla también apaga la plática: si no, se iba de la pantalla pero seguía oyendo 20 segundos |

## Decisiones y por qué
| Decisión | Alternativa | Motivo |
|---|---|---|
| Pixel art en un lienzo | Lottie | Control total de cada emoción y mezcla |
| Detección de manos y cara en el equipo | Enviar video a una API | Privacidad, sin costo y sin latencia de red |
| Modelo elige las emociones con una etiqueta | Analizar el texto después | La emoción llega antes que las palabras |
| SQLite como fuente de la verdad | Solo base de vectores | Qdrant y Obsidian se pueden reconstruir |
| Herramientas para buscar, mirar y olvidar | Etiquetas de texto | Las etiquetas fallaban: con el precio del dólar inventaba la respuesta |
| Haiku 5.5 sin razonamiento | Modelos que razonan | En conversación en vivo importa empezar a hablar pronto |
| Turso | Otra base en la nube | Compatible con SQLite y con plan gratis |
| Vosk con palabras parecidas para "Oye Nova" | Solo la frase | Solo la frase se activaba por error casi siempre |
| Whisper local para transcribir | Servicio de pago | Sin costo y sin mandar audio a internet |
| Electron | Tauri | Sin instalar Rust, y usa el mismo Chromium donde ya se probó la animación |
| Teclear sin Enter, con reglas en el código | Confiar en lo que diga el prompt | Una instrucción se puede ignorar; un carácter que se quita antes de teclear, no |
| Un redactor aparte, sin herramientas ni memoria | Darle la captura a Nova | Un mensaje en pantalla que intente darle órdenes solo puede cambiar el texto, que tú revisas |
| InsightFace dentro de la Mac, sin su paquete de Python | Pedirle a Claude que identifique caras | Claude no identifica personas por su cara, y así la huella no sale del equipo |
| Observaciones con valores fijos, contadas por código | Guardar fotos o dejar que el modelo resuma | Sin fotos en disco, sin datos de cuerpo o salud, y sin costumbres inventadas |

## Cifras para contar
| Qué se midió | Resultado |
|---|---|
| Hasta oírla con `grok-4.5` | Unos 10 s |
| Hasta oírla con un modelo sin razonamiento | 0.85 a 1.8 s |
| Hasta oírla con Haiku y ElevenLabs | 0.96 a 1.9 s, con un caso aislado de 6.6 s |
| Decidir buscar con etiqueta de texto | 9 de 16 veces |
| Decidir buscar con herramienta | 16 de 16 veces |
| Una explicación: palabras antes y después | 353 a 180 con Grok; 99 con Haiku |
| "Oye Nova" solo con la frase | 10 de 10 detectadas, 14 de 18 falsas |
| "Oye Nova" con palabras parecidas | 10 de 10 detectadas, 1 a 2 de 18 falsas |
| "Oye Nova" y Whisper juntos | 2 de 18 falsas llegaban a Whisper, y las dos se descartaron sin gastar turno |
| Transcripción local con Whisper | Unos 0.1 s por frase corta, después de la carga inicial |
| Costo por turno con Haiku | Unos $0.002 de Claude; una búsqueda, unos $0.012 |
| Plan de voz | $22 al mes, unos 485 turnos |

## Errores que valen la pena contar
- **Siempre neutra:** el prompt le permitía estarlo; las emociones existían, pero no se usaban.
- **La cámara parecía muerta:** el navegador esperaba un permiso sin avisar en pantalla.
- **Negaba a su creador:** nadie le había dicho quién la hizo.
- **Se negaba a ayudar:** demasiada libertad la llevó a rechazar peticiones; se acotó para que opine y ayude.
- **Inventaba precios:** sin obligarla a buscar, respondía datos actuales de memoria.
- **Una pestaña cerrada tumbaba el turno:** avisar a una conexión muerta rompía la conversación.
- **"Olvidar" dejaba rastro:** el texto seguía en el registro de sincronización.
- **La primera migración perdió recuerdos:** la comprobación por huellas lo detectó antes de usarla.
- **Decía mi nombre a cada rato.** En una plática de 20 respuestas lo dijo 16 veces. Con reglas de estilo explícitas bajó a 0, sin perder la calidez.
- **El botón que la dejaba sorda.** El micrófono se apagaba y Nova, oculta, no daba ninguna señal; ese botón se fue a la barra de menú.
- **Se quedaba "sorda" al llamarla.** Sí oía y respondía, pero sin sonido: al abrir con el micrófono ya encendido, nunca se preparaba la salida de audio. La lección: probar también la segunda apertura.

## Cómo seguir la documentación
Cada cambio que se sube a `main` debe actualizar `CHANGELOG.md` y, si cambia la historia, esta
bitácora. Cada avance visible lleva una etiqueta de versión.
