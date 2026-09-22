"""Найти карту в кадре и выпрямить её.

Это тот самый шаг, которого сканеру не хватало. Без него карту приходится
класть в нарисованную на экране рамку: отпечаток арта считается по неизменной
доле кадра, и стоит карте повернуться на восемь градусов или сползти на шесть
процентов, как вырезается уже другой кусок картинки. Измерено: до 4 градусов
поворота узнаётся всё, на 6 -- три четверти, на 12 -- ничего.

С выпрямлением обе эти оси исчезают. Карта ищется в кадре как четырёхугольник,
её углы приводятся к прямоугольнику нужных пропорций, и дальше хеш считает уже
по карте, а не по кадру. Как она лежала -- неважно.

Порядок ровно такой же, как в открытых распознавателях карт (и, судя по
поведению, в ManaBox): уменьшить кадр, выровнять освещение, получить границы,
взять контуры, отобрать среди них четырёхугольники с пропорциями карты,
выпрямить перспективным преобразованием.

Чего этот шаг не умеет: разбирать карты, лежащие внахлёст. У них нет
собственного замкнутого контура -- видно только полосу. Для пачки есть другой
путь (app/pile.py, чтение имён), и это не обход трудности, а разные задачи.
"""

from __future__ import annotations

from typing import Any

try:
    import cv2
    import numpy as np
    DEPS_OK = True
except ImportError:                                      # pragma: no cover
    cv2 = None                                           # type: ignore[assignment]
    np = None                                            # type: ignore[assignment]
    DEPS_OK = False

# Кадр уменьшается до этой стороны: искать контуры по четырём мегапикселям
# незачем, а на быстродействие это влияет вчетверо.
WORK_SIDE = 1000
# Выпрямленная карта: пропорции 63 x 88 мм и разрешение, с запасом
# достаточное для отпечатка (он считается по 32 x 32).
CARD_W, CARD_H = 488, 680
# Доля кадра, меньше которой четырёхугольник -- это не карта, а мусор.
MIN_AREA = 0.02
MAX_AREA = 0.98
# Насколько пропорции найденного могут отличаться от карточных.
RATIO = CARD_H / CARD_W
RATIO_SLACK = 0.22


def _order_corners(pts: "np.ndarray") -> "np.ndarray":
    """Углы по обходу контура, начиная с короткой стороны.

    Обычный способ -- «левый верхний тот, у кого x+y наименьшая» -- работает,
    пока карта лежит почти ровно, и разваливается после сорока пяти градусов:
    углы меняются местами, карта выпрямляется повёрнутой, и хеш получается
    чужой. Измерено: до 35° узнавалось всё, на 60° -- ничего.

    Поэтому углы сортируются по направлению от центра (это даёт обход по
    кругу при любом повороте), обход разворачивается в ту же сторону, что у
    прямоугольника-цели (иначе карта выйдет зеркальной), и начало ставится на
    короткую сторону -- тогда она станет верхом, а карта -- вертикальной.

    Остаётся единственная неоднозначность: карта вверх ногами. Её снимает уже
    поиск, пробуя оба разворота, -- по картинке это не решается, а по
    отпечатку решается мгновенно.
    """
    pts = pts.reshape(4, 2).astype("float32")
    centre = pts.mean(axis=0)
    order = np.argsort(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))
    pts = pts[order]

    # Знак площади по формуле шнурков: обход должен совпасть с обходом цели,
    # иначе перспективное преобразование отразит карту.
    area = 0.0
    for i in range(4):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % 4]
        area += float(x0 * y1 - x1 * y0)
    if area < 0:
        pts = pts[::-1]

    sides = [float(np.linalg.norm(pts[(i + 1) % 4] - pts[i])) for i in range(4)]
    start = int(np.argmin(sides))
    return np.roll(pts, -start, axis=0)


def _edges(bgr: "np.ndarray") -> "np.ndarray":
    """Границы предметов в кадре, устойчиво к освещению.

    Свет выравнивается CLAHE по яркостному каналу LAB: при обычном пороге
    карта в тени и карта под лампой требуют разных порогов, а после
    выравнивания -- одного.
    """
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
    grey = cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)
    grey = cv2.cvtColor(grey, cv2.COLOR_BGR2GRAY)
    grey = cv2.GaussianBlur(grey, (5, 5), 0)
    edges = cv2.Canny(grey, 40, 120)
    # Замыкаем разрывы: край карты на пёстром фоне рвётся, а контур должен
    # быть замкнутым, иначе его не найти.
    return cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)


def _quads(edges: "np.ndarray", frame_area: float) -> list["np.ndarray"]:
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found: list[np.ndarray] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < frame_area * MIN_AREA or area > frame_area * MAX_AREA:
            continue
        hull = cv2.convexHull(contour)
        peri = cv2.arcLength(hull, True)
        quad = cv2.approxPolyDP(hull, 0.02 * peri, True)
        if len(quad) != 4 or not cv2.isContourConvex(quad):
            # Скруглённые углы карты иногда дают пять точек -- пробуем грубее.
            quad = cv2.approxPolyDP(hull, 0.05 * peri, True)
            if len(quad) != 4 or not cv2.isContourConvex(quad):
                continue
        corners = _order_corners(quad)
        width = max(np.linalg.norm(corners[0] - corners[1]),
                    np.linalg.norm(corners[3] - corners[2]))
        height = max(np.linalg.norm(corners[0] - corners[3]),
                     np.linalg.norm(corners[1] - corners[2]))
        if width < 20 or height < 20:
            continue
        ratio = height / width
        # Карта может лежать и боком: тогда пропорции обратные.
        if not (abs(ratio - RATIO) <= RATIO_SLACK
                or abs(1 / ratio - RATIO) <= RATIO_SLACK):
            continue
        found.append(corners)
    return found


def _warp(bgr: "np.ndarray", corners: "np.ndarray") -> "np.ndarray":
    """Выпрямить карту в прямоугольник 488 x 680.

    Углы уже разложены так, что первая сторона -- короткая, то есть верх
    карты: специально доворачивать ничего не нужно.
    """
    target = np.array([[0, 0], [CARD_W - 1, 0],
                       [CARD_W - 1, CARD_H - 1], [0, CARD_H - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(corners.astype("float32"), target)
    return cv2.warpPerspective(bgr, matrix, (CARD_W, CARD_H))


def find_cards(data: bytes, limit: int = 4) -> list[dict[str, Any]]:
    """Карты в кадре: выпрямленная картинка каждой и её углы в кадре.

    Углы возвращаются в долях кадра, а не в пикселях: кадр по дороге
    уменьшался, а рисовать обводку интерфейсу надо поверх своего видео.
    """
    if not DEPS_OK:
        return []
    buf = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if frame is None:
        return []

    height, width = frame.shape[:2]
    scale = WORK_SIDE / max(height, width)
    if scale < 1:
        frame = cv2.resize(frame, (int(width * scale), int(height * scale)),
                           interpolation=cv2.INTER_AREA)
    height, width = frame.shape[:2]

    quads = _quads(_edges(frame), float(height * width))
    quads.sort(key=lambda c: -cv2.contourArea(c.astype("float32")))

    out: list[dict[str, Any]] = []
    for corners in quads[:limit]:
        ok, buf2 = cv2.imencode(".jpg", _warp(frame, corners),
                                [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            continue
        out.append({
            "image": buf2.tobytes(),
            "corners": [[round(float(x) / width, 4), round(float(y) / height, 4)]
                        for x, y in corners],
            "area": round(float(cv2.contourArea(corners.astype("float32")))
                          / (width * height), 4),
        })
    return out


__all__ = ["CARD_H", "CARD_W", "DEPS_OK", "find_cards"]
