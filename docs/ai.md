# AI-модели KörGöz

Все модели работают локально, на CPU, через ONNX Runtime или OpenCV. Видео не
отправляется ни в какие внешние сервисы.

## Используемые модели

| Задача | Модель | Файл | Лицензия | Источник |
|---|---|---|---|---|
| Детекция людей | YOLOX-s (по умолчанию) | `models/yolox_s.onnx` (36 МБ, вход 640×640) | Apache-2.0 | [Megvii YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) release 0.1.1rc0 |
| Детекция людей (быстрая) | YOLOX-tiny | `models/yolox_tiny.onnx` (20 МБ, вход 416×416) | Apache-2.0 | там же |
| Детекция лиц | YuNet 2023mar | `models/face_detection_yunet_2023mar.onnx` (0.2 МБ) | MIT | [OpenCV Model Zoo](https://github.com/opencv/opencv_zoo) |
| Embeddings лиц | SFace 2021dec | `models/face_recognition_sface_2021dec.onnx` (37 МБ, вектор 128-d) | Apache-2.0 | OpenCV Model Zoo |

Установка (один раз, нужен интернет):

```bash
python -m scripts.download_models            # модели (SHA-256 проверяется)
python -m scripts.download_models --samples  # + тестовое видео и фото для тестов
```

### Лицензии: что проверено и что нет

- Код и веса YOLOX опубликованы Megvii под Apache-2.0, коммерческое использование разрешено.
  Модели обучены на COCO. Аннотации COCO распространяются под CC BY 4.0, изображения
  взяты с Flickr под разными лицензиями. Для коммерческого продукта стоит подтвердить
  у юриста, что веса, обученные на COCO, можно использовать.
- YuNet — MIT. SFace — Apache-2.0.
- **Не используются:** Ultralytics YOLOv8/v11 (AGPL-3.0) и модели InsightFace
  (только некоммерческое использование).
- Тестовые медиа (`vtest.avi`, `lena.jpg`) взяты из репозитория OpenCV. Портреты
  `biden_*`, `harris_*`, `obama_1` — официальные фото правительства США с Wikimedia
  Commons (public domain). Всё это нужно только для локальных тестов и в git не
  попадает (`data/` в `.gitignore`).

## Абстракции

Остальная система не знает, какая модель стоит внутри:

```
Detector (app/detection/base.py)          detect(image) -> list[DetectionResult(bbox, confidence, class_id)]
└── YoloxPersonDetector                    app/detection/person_detector.py

FaceDetector (app/recognition/detector.py) detect(image) -> list[FaceDetection(bbox, confidence, landmarks)]
└── YuNetFaceDetector

FaceEmbeddingProvider (app/recognition/embedding.py)  embed(image, face) -> вектор (L2-нормированный)
└── SFaceProvider

VectorStore (app/vector_store/base.py)    add_embedding / search / delete_embedding / delete_person / health_check
└── QdrantVectorStore                     метрика cosine, payload: person_id, model_name
```

Модели создаются только в `app/pipeline/factory.py`. Чтобы заменить модель, напиши
новый класс-наследник и поправь фабрику. Трекинг, события и API менять не нужно.

## Как работает YOLOX (кратко)

1. **Letterbox.** Кадр уменьшается с сохранением пропорций, свободное место заливается
   серым (114). Формат — BGR 0..255 без нормализации.
2. **Сеть.** Возвращает 8400 строк (для 640px) по 85 чисел: смещения `cx, cy, w, h`
   относительно ячейки сетки, objectness и 80 вероятностей классов COCO.
3. **Декодирование.** Смещения переводятся в пиксели по сеткам со страйдами 8/16/32.
4. **Фильтрация.** `score = objectness × P(person)`, затем отсечение по
   `PERSON_CONFIDENCE_THRESHOLD`.
5. **NMS.** Из пересекающихся рамок (IoU > `PERSON_NMS_THRESHOLD`) остаётся лучшая.
6. Координаты пересчитываются обратно в размер исходного кадра.

## Трекинг

ByteTrack-трекер (`app/tracking/`) — это не нейросеть: он сопоставляет рамки по геометрии,
а движение предсказывает фильтром Калмана. Обновление на ~6 людях занимает ~0.6 мс.
На 30 с тестового видео самые длинные треки держались на протяжении 250+ кадров
без смены номера.

## Распознавание лиц (Phase 5)

```
лицо (YuNet, 5 точек) → FaceQualityChecker → SFace: alignCrop + feature → Qdrant search → порог
                         размер, резкость,      вектор 128-d                  лучший     Match(person_id, score)
                         поворот головы                                       кандидат   или Unknown
```

- **Quality check** (`app/recognition/quality.py`) отсекает лица, по которым
  вектор будет мусорным:
  - размер — короткая сторона рамки (`FACE_MIN_SIZE`, для регистрации `FACE_REGISTRATION_MIN_SIZE`);
  - резкость — дисперсия Лапласиана на вырезке 112×112 (`FACE_MIN_SHARPNESS`);
  - поворот — насколько нос смещён от середины между глазами (`FACE_MAX_YAW`).
- **Без forced matching.** Если лучший кандидат ниже `FACE_MATCH_THRESHOLD`, результат
  `Unknown`, даже если это «самый похожий» человек.
- **Калибровка порога** (cosine similarity SFace, тестовые портреты, разные годы съёмки):

  | Пары | Сходство |
  |---|---|
  | один человек (biden_1/biden_2, harris_1/harris_2) | 0.72–0.78 |
  | разные люди (все остальные пары, включая lena) | −0.04 … 0.24 |

  Порог 0.40 стоит посередине. OpenCV рекомендует 0.363 (откалибровано на LFW).
  Студийные портреты — лучший случай; на вебке сходство своего человека ниже.
- **Распознавание по трекам, а не по кадрам** (`RecognitionSink`, `app/recognition/sink.py`):
  - лица берутся из детекции на всём кадре; лицо относится к треку, если его центр
    внутри рамки ровно одного трека (лицо в зоне перекрытия двух людей пропускается);
  - попытка только на кадрах с детекцией (`fresh`), иначе рамки лиц устарели;
  - не узнанный трек пробуется не чаще раза в `RECOGNITION_INTERVAL_SECONDS`;
    узнанный — больше не пробуется до конца трека;
  - Qdrant опрашивается при каждой попытке, поэтому человек, зарегистрированный через
    API, узнаётся сразу, без перезапуска воркера.
- Регистрация (`POST /persons`): фото декодируется в памяти, большие уменьшаются до
  1600 px по длинной стороне. Порядок записи: строка `Person` (без commit) → вектор в
  Qdrant → `FaceEmbedding` → commit. Если Qdrant упал — откат, если упал commit —
  вектор удаляется из Qdrant.

## Когда запускаются модели

- **Детекция людей** запускается на каждом `DETECTION_INTERVAL`-м кадре. Между
  детекциями используются последние рамки. В Phase 4 трекер будет предсказывать
  их движение.
- **Детекция лиц и SFace** работают **только в режиме `recognition`**. В режиме
  `anonymous` модели лиц даже не загружаются (privacy by design). Распознаванию
  нужен трекинг (`TRACKING_ENABLED=true`).
- Если модель не загрузилась (нет файла, битый файл), воркер не падает: захват
  видео продолжается, а `/health` показывает `"ai": "unavailable"`.

## Замеры производительности

Машина: Intel Core Ultra 5 125U (14 логических ядер), без GPU, ONNX Runtime 1.30 CPU.
Видео: `vtest.avi`, 768×576. Замер только детекции, без захвата, трекинга и кодирования.

| Модель | mean | p50 | p95 | ≈ детекций/с |
|---|---|---|---|---|
| YOLOX-s 640 | 75.8 мс | 75.7 мс | 79.6 мс | 13 |
| YOLOX-tiny 416 | 21–40 мс | — | 49 мс | 25–48 |
| YuNet (лица, весь кадр) | 12.9 мс | 13.3 мс | 14.8 мс | 78 |
| SFace (одно лицо: выравнивание + вектор) | 5.3 мс | — | — | ~190 |
| `identify` целиком (quality + SFace + поиск в локальном Qdrant) | 9.2 мс | — | — | ~110 |

У YOLOX-tiny результаты сильно скачут между запусками (21 и 40 мс). Скорее всего,
это троттлинг ноутбучного U-процессора. Для стабильных цифр нужен длинный прогон
на питании от сети.

Сквозной прогон (камера-файл 10 FPS, `DETECTION_INTERVAL=3`, YOLOX-s): обрабатываются
все 10 кадров/с, детекция занимает ~76 мс.

Свой замер:

```bash
python -m scripts.benchmark_detector                          # YOLOX-s
python -m scripts.benchmark_detector --model models/yolox_tiny.onnx --faces
python -m scripts.benchmark_detector --threads 4              # ограничить потоки ONNX
```

### Настройка под слабое железо

- `PERSON_DETECTOR_MODEL_PATH=models/yolox_tiny.onnx` — в 2–3 раза быстрее, чуть хуже
  находит мелких и далёких людей.
- `DETECTION_INTERVAL=5` — детекция реже, трекер (Phase 4) заполняет промежутки.
- `CAMERA_MAX_FPS=10` — меньше кадров на обработку.
- `ONNX_NUM_THREADS` — при нескольких камерах ограничь потоки, чтобы камеры не
  отнимали друг у друга CPU.

## Тесты моделей

```bash
pytest -m ai     # YOLOX находит пешеходов, YuNet — одно лицо, SFace различает людей
                 # на портретах и узнаёт зарегистрированного по другому фото
```

Обычный `pytest` эти тесты не запускает. Пре- и постобработка YOLOX покрыта
unit-тестами без загрузки модели.
