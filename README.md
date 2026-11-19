# e-paper morning dashboard

for a seeed reterminal e1001 / e1002 (800x480).

shows: today's list from google keep, brooklyn weather, uv now + for the day,
today's exercise, a daily "life" checklist, and birds seen near you lately
(with a bird of the day photo).

## how it works

```
github actions (every 30 min)
  -> build.py pulls keep + open-meteo, renders site/index.html
  -> publishes to github pages
sensecraft hmi "web content"
  -> screenshots that url on a timer and pushes it to the reterminal
```

no computer needs to stay on. weather is open-meteo (free, no key).

## setup

### 1. try the layout locally

```
pip install -r requirements.txt
python build.py --mock
open site/index.html
```

edit `config.yaml` for your routine, weekly exercise, and keep note name.
set `display.color: true` if you have the color e1002.

### 2. get a keep master token

google keep has no public api for personal accounts, so this uses
[gkeepapi](https://github.com/kiwiz/gkeepapi), which talks to the same api
the android app uses. it works well but google could break it someday.

run `python get_master_token.py` and follow the steps at the top of that file.

### 3. put it on github

1. make a new repo and push this folder to it.
2. settings > secrets and variables > actions > new repository secret. add:
   - `KEEP_EMAIL`: your google email
   - `KEEP_MASTER_TOKEN`: the token from step 2
   - `EBIRD_KEY` (optional): free key from https://ebird.org/api/keygen. without it,
     the bird list is a fixed set of common brooklyn birds from config.yaml.
   - `DASH_PATH`: a random string, like `d/k3v9xq2m7p`. the page will live at
     that path instead of the root.
3. settings > pages > source: **github actions**.
4. actions tab > "build dashboard" > run workflow. when it finishes, your page is at
   `https://<your-username>.github.io/<repo-name>/<DASH_PATH>/`

**privacy note:** github pages are public (free plan). the random `DASH_PATH`
keeps people from stumbling onto it, but anyone with the link can see your
list. the repo itself also needs to be public for free pages, so your
`config.yaml` (routine, exercise) is visible. if that bugs you, put routine
and exercise in keep notes instead (see `routine_note` / `exercise_note` in
the config) and nothing personal lives in the repo.

### 4. point the reterminal at it

1. go to https://sensecraft.seeed.cc/hmi and pair your reterminal.
2. workspace > web content (or my pages > + web content).
3. paste your page url, preview, then deploy.
4. set the refresh interval to 30 min to match the build.

## how the keep note is read

the note named in `keep.today_note` can be a plain note or a checklist.

```
ongoing: finish the bookcase bench
remember: you can only do so much in a day

thursday 11/19
kickoff call 10am
remember: bring the charger
dinner 7:30

friday 11/20
laundry
```

- **day headers** start a section. any of these work: `thursday`, `thurs 11/19`,
  `11/19`, `nov 19`, `Thursday, November 19th`. only today's section shows.
  if a header has a date, the date decides. if it's just a weekday name, it
  matches every week, so clear out old days or add the date.
- **`ongoing:`** shows every day in a box at the bottom of the list, wherever it is
  in the note. if there are none, the box shows an affirmation that changes daily
  (edit the list in `AFFIRMATIONS` in build.py).
- **`remember:`** shows in bold.
- **lines above the first day header** show every day.
- **checked-off items** (in checklist mode) are hidden.

## workouts

`schedule` in config.yaml says what happens each day. if a name there matches
a workout under `workouts`, the screen lists its exercises. put two spaces
between the exercise and the sets (`goblet squat  2×10`) and the sets line up
on the right.

## files

- `build.py`: fetches everything and renders the page
- `templates/dash.html`: the layout (plain html/css, edit freely)
- `config.yaml`: location, routine, exercise, keep note names
- `get_master_token.py`: one-time keep login helper
- `.github/workflows/build.yml`: the 30-minute schedule

## life list

`life` in config.yaml. items with `every: 3` only show every third day,
counting from `start`. change `start` to a day you actually did it and the
schedule lines up from there.

## birds

with an `EBIRD_KEY`, the script pulls every species reported on ebird within
`radius_km` of you in the last `days` days, sorted by how many were counted.
the bird of the day is anything ebird flags as rare nearby. if nothing's rare,
it rotates daily through the list (skipping the 3 most common, so it's not
always a pigeon). the photo comes from that bird's wikipedia page.
