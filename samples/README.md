# Material de prueba

`ibm-future-computing-360p.webm` es la transcodificación VP9 360p de
“A lab for the future of computing”, de IBM Research (70,6 segundos),
distribuida bajo CC BY 3.0. Fuente y licencia:

https://commons.wikimedia.org/wiki/File:A_lab_for_the_future_of_computing.webm

- `ibm-future-computing.en.srt`: subtítulos ingleses publicados en Wikimedia;
  sirven como referencia humana para evaluar el reconocimiento.
- `ibm-future-computing.es.srt`: traducción de prueba preparada para este
  prototipo; sirve para una comparación orientativa de TranslateGemma, no se
  presenta como ground truth independiente.

`nerdearla-kubernetes-es.mp4` contiene 90 segundos en español de una charla de
Nerdearla sobre bases de datos y Kubernetes. Su SRT recortado permite evaluar
ASR español; al ser un caption automático de origen, el WER es orientativo y no
un ground truth humano.

En `/studio`, elegir la dirección y **Simular con video** reproduce cualquiera
de los videos a velocidad real por el mismo camino de audio que utiliza el
micrófono. Los SRT se usan sólo desde los scripts de calidad y no aparecen en el
front público.
