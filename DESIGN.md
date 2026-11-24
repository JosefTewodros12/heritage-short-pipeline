# Film Design & Audience Testing

## 1. Audience & Intent

- **Target Audience:** Family members, relatives, and peers who value family heritage, storytelling, and everyday cultural traditions.
- **Viewing Context:** Mobile screens (9:16 vertical) and desktop/TV (16:9 horizontal).
- **Intent:** Help viewers feel connected to family memory and understand the core lesson or proverb at the heart of the story by the end of the film.

## 2. Shot-by-Shot Purpose

| Shot ID   | Purpose / Reason in Story                                                 |
| :-------- | :------------------------------------------------------------------------ |
| `shot_01` | Establish setting, mood, and time of day so viewers orient immediately.   |
| `shot_02` | Introduce the central family ritual, object, or character presence.       |
| `shot_03` | Build narrative context and emotional warmth through visual detail.       |
| `shot_04` | Mark a key story beat or turning moment in the memory.                    |
| `shot_05` | Deepen connection through a closer view of gesture, expression, or craft. |
| `shot_06` | Connect the memory to a broader reflection or family proverb.             |
| `shot_07` | Bring emotional resolution and lingering resonance before the close.      |
| `shot_08` | Close the narrative arc cleanly leading into the AI disclosure end card.  |

## 3. User Test 1: Radio Cut (At Least 3 Audience Members)

- **Participants:** Listener 1, Listener 2, Listener 3 (family/peers)
- **What We Tested:** Narration pacing, clarity, and emotional flow of the story before final video assembly.
- **What They Said:** The evening coffee story and proverb were easy to follow, though pacing felt slightly quick in places.
- **What Changed in `storyboard.json`:** Kept the core proverb and adjusted narration wording/timing for smoother flow.

## 4. User Test 2: Near-Final Cut (At Least 3 Audience Members)

- **Participants:** Viewer 1, Viewer 2, Viewer 3 (family/peers)
- **What We Tested:** Visual continuity, subtitle readability, music ducking under narration, and overall story impact.
- **What They Said:** Narration stayed clear over the background sound, subtitles were readable, and the ending felt warm.
- **What Changed in `storyboard.json` / Edit:** Verified shot sequence and exported both `film_16x9.mp4` and `film_9x16.mp4` cleanly.
