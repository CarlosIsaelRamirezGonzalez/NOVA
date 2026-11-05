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
| 14. Lo que sigue | Próxima | Decir "Oye Nova" | App en la Mac con palabra de activación |

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

## Cómo seguir la documentación
Cada cambio que se sube a `main` debe actualizar `CHANGELOG.md` y, si cambia la historia, esta
bitácora. Cada avance visible lleva una etiqueta de versión.
