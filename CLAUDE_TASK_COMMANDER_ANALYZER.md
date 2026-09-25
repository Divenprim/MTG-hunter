# Задача: Commander Deck Analyzer для MTG Hunter

Нужно добавить в MTG Hunter полноценный модуль автоматического анализа Commander-колод.

## Что должен выдавать модуль

Для любой Commander-колоды система должна рассчитывать и объяснять:

- ориентировочный Commander Bracket: B1 / B2 / B3 / B4 / B5;
- Power Score 0–100;
- Salt Score 0–100;
- профиль колоды по отдельным осям;
- причины, почему дека получила именно такой результат;
- карты и взаимодействия, которые сильнее всего повлияли на оценку.

Bracket, Power и Salt — независимые показатели и не должны сводиться к одной общей формуле.

Пример результата:

```
B3 — Upgraded
Confidence: 87%

Power: 78/100
Salt: 42/100

Speed:           74
Consistency:     86
Interaction:     71
Resilience:      67
Fast Mana:       63
Tutors:          88
Combo:           91
Stax:             7
Resource Denial:  4
```

И объяснение:

```
Почему B3:
- высокая плотность туторов;
- есть двухкарточная combo;
- одна combo piece находится в command zone;
- interaction package сильный;
- fast mana и free interaction пока недостаточно для уверенного B4.
```

## Архитектурная идея

Анализатор должен работать как отдельный слой Deck Intelligence поверх уже существующих возможностей MTG Hunter.

Общий pipeline:

```
Deck
  ↓
Card / deck feature extraction
  ↓
Combo + win condition analysis
  ↓
Deck feature vector
  ↓
┌───────────────┬───────────────┬──────────────┐
│ Bracket Engine│ Power Engine  │ Salt Engine  │
└───────────────┴───────────────┴──────────────┘
  ↓
Explainable analysis result
```

Нужно по максимуму использовать то, что в проекте уже есть:

- локальную базу карт;
- Scryfall metadata;
- Scryfall Tagger / card tags;
- Commander Spellbook;
- текущий combo-анализ;
- win routes;
- deck shape;
- goldfish;
- commander / deck storage;
- существующие данные о функциях карт.

Не нужно строить параллельную систему, которая заново изобретает уже имеющиеся сущности.

## Deck Feature Vector

Анализатор должен собирать единое представление колоды, в котором есть как минимум:

- commander;
- Game Changers;
- tutors;
- unconditional / broad / narrow tutors;
- fast mana;
- обычная ramp;
- free interaction;
- counterspells;
- removal;
- protection;
- board wipes;
- card draw;
- recursion;
- resilience;
- stax;
- resource denial;
- mass land destruction;
- extra turns;
- discard / hand pressure;
- hard locks;
- complete combos;
- compact combos;
- commander-based combos;
- win conditions;
- average mana value / curve signals;
- commander dependency;
- commander as engine;
- commander as combo piece;
- unknown / unresolved cards.

## Combo analysis

Combo должна анализироваться не бинарно.

Нужно учитывать:

- число карт в combo;
- участие командира;
- mana requirement;
- deterministic win или нет;
- infinite damage / mana / draw / tokens / loop / lock / value engine;
- насколько легко combo собирать;
- сколько туторов реально ищут её части;
- сколько частей доступно из command zone;
- насколько компактна combo.

Нужна отдельная метрика условного Combo Accessibility / Combo Consistency.

Пример:

```
Combo A + B

pieces: 2
commander piece: yes
useful tutors: 7
mana requirement: low
deterministic win: yes

Accessibility: 92/100
```

И та же по смыслу, но четырёхкарточная combo без туторов должна иметь заметно более низкую доступность.

## Power Score

Power должен отражать реальную силу колоды, а не “солёность”.

Основные измерения:

- speed;
- consistency;
- interaction;
- resilience;
- mana acceleration;
- tutoring;
- combo potential;
- card advantage;
- commander engine;
- win condition efficiency.

Итоговый Power не должен быть простым средним.

Нужно учитывать нелинейные сочетания, например:

- compact combo + высокая плотность туторов;
- fast mana + compact win condition;
- commander combo piece + tutor density;
- strong free interaction + fast game plan.

## Salt Score

Salt должен отражать насколько игровой план склонен создавать неприятный или ограничивающий игровой опыт, а не насколько дека сильная.

Основные сигналы:

- stax;
- hard locks;
- resource denial;
- mass land destruction;
- repeatable discard;
- extra turn loops;
- repeatable extra turns;
- game monopoly / solitaire turns;
- oppressive denial engines.

Важно:

- сильный removal сам по себе не должен делать деку “солёной”;
- хорошая counterspell package не должна автоматически повышать Salt сильно;
- медленная stax-дека может иметь Power ниже, а Salt сильно выше;
- быстрая combo-дека может иметь Power очень высокий, а Salt умеренный.

## Bracket Engine

Bracket нельзя определять как диапазон Power Score.

Нужно учитывать:

- актуальные правила Commander Brackets;
- актуальный список Game Changers;
- ограничения конкретных brackets;
- mass land denial;
- extra turns;
- intentional compact infinite combos;
- deck intent;
- optimized profile;
- cEDH profile.

Для каждого bracket желательно уметь показывать:

```
compatible: true / false
violations: [...]
warnings: [...]
```

Итог может быть, например:

```
Bracket: B3
Confidence: 86%
Borderline: B3/B4
```

Это лучше, чем насильно присваивать жёсткий класс, если дека реально находится на границе.

B4 должен определяться как optimized-profile, а не как “слишком много очков”.

B5 / cEDH тоже не должен присваиваться любой очень сильной casual-деке. Для cEDH нужен отдельный совокупный профиль.

## Confidence

У результата должна быть confidence-оценка.

Она должна снижаться, если:

- часть карт не распознана;
- Commander Spellbook недоступен;
- часть tags отсутствует;
- commander не определён;
- decklist неполный;
- какие-то ключевые метрики не удалось посчитать.

Система должна честно показывать, где результат менее надёжен.

## Explainability

Каждый score должен иметь contributors.

Например:

```
Tutoring: 82

Вклад:
- Demonic Tutor
- Vampiric Tutor
- Imperial Seal
- Enlightened Tutor
```

Для итогового результата желательно показывать условные причины:

```
Основные причины Power 81:
+ высокая tutor density
+ двухкарточная deterministic combo
+ combo piece в command zone
+ fast mana
+ free interaction
```

И отдельно:

```
Основные причины Salt 67:
+ stax density
+ repeatable mana denial
+ hard lock
+ extra turn loop
```

## Impact cards

Желательно определять карты, которые сильнее всего двигают:

- Power;
- Salt;
- Bracket.

Пример:

```
Card X
power impact: high
salt impact: low
bracket effect: none

Card Y
power impact: medium
salt impact: high
bracket effect: Game Changer
```

## What-if analysis

Архитектура должна позволять в дальнейшем сделать режим:

```
что изменится, если добавить / убрать карту
```

Пример:

```
Before:
B3
Power 74
Salt 28

After adding Card X:
B4 borderline
Power 81
Salt 29

Причина:
- combo стала двухкарточной;
- новый tutor ищет обе части;
- выросла consistency.
```

## Rules / Game Changers

Commander Brackets и Game Changers меняются.

Поэтому актуальные правила и списки должны быть версионируемыми и обновляемыми, а результат анализа должен уметь показывать, по какой версии правил он считался.

Пример:

```
Rules version: 2026-02-09
Commander Brackets: Beta
Game Changers updated: 2026-02-09
```

## UI

Анализ должен быть встроен в существующий deck workflow MTG Hunter.

Нужна понятная верхняя сводка:

```
B3 — Upgraded        Confidence 87%

Power  ████████░░ 78
Salt   █████░░░░░ 42
```

Ниже отдельные метрики:

```
Speed
Consistency
Interaction
Resilience
Fast Mana
Tutors
Combo
Stax
Resource Denial
```

Должна быть секция “Почему такой результат”.

Combo-summary не должен дублировать уже существующий подробный combo-интерфейс.

## API / data model

Нужен единый результат анализа, пригодный и для UI, и для тестов, и для будущего what-if режима.

Пример структуры ответа:

```json
{
  "bracket": {
    "value": 3,
    "name": "Upgraded",
    "confidence": 0.87,
    "borderline": null
  },
  "power": {
    "score": 78
  },
  "salt": {
    "score": 42
  },
  "metrics": {
    "speed": 74,
    "consistency": 86,
    "interaction": 71,
    "resilience": 67,
    "fast_mana": 63,
    "tutoring": 88,
    "combo": 91,
    "stax": 7,
    "resource_denial": 4
  },
  "game_changers": [],
  "combos": {},
  "reasons": [],
  "impact_cards": [],
  "warnings": [],
  "rules": {}
}
```

Точная внутренняя реализация и структура кода остаются на усмотрение исполнителя после изучения проекта.

## Тестирование

Нужно добавить нормальные тесты.

Минимально проверить:

1. casual deck без GC / compact combo / fast mana не становится B4;
2. commander-based combo получает выше consistency/accessibility, чем такая же combo без commander piece;
3. рост tutor density увеличивает consistency / power;
4. stax заметно увеличивает Salt;
5. removal увеличивает Power, но почти не влияет на Salt;
6. mass land destruction сильно влияет на Salt и bracket compatibility;
7. unknown cards уменьшают confidence;
8. отсутствие combo database не ломает анализ;
9. non-Commander deck не получает бессмысленный bracket;
10. high-power casual не превращается автоматически в cEDH.

Кроме unit tests, прогнать анализ на нескольких реальных Commander decklists разных уровней:

- casual;
- upgraded;
- optimized;
- cEDH;
- high-salt stax / denial.

Для реальных дек лучше проверять диапазоны и здравый смысл результата, а не жёсткое равенство одному числу.

## Главное требование к качеству

Система должна отвечать не только:

> “Какой bracket?”

а:

> “Как эта колода играет, насколько быстро и стабильно реализует план, какие у неё win conditions, насколько она ограничивает других игроков и почему именно это приводит к такой оценке.”

Итог должен быть объяснимым, воспроизводимым и полезным для Rule 0 discussion.
