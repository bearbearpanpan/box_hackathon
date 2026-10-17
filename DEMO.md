# Demo script: Reality Check chat agent

A 5-minute live demo using `chat.py` with **3 contracts in Box**
(`CTR-0001`, `CTR-0002`, `CTR-0003` in the contracts folder).

## Before you present

```bash
python3 agent/lambda/tools/check_config.py   # Box ✅ + Bedrock ✅
python3 chat.py                              # start it now; first question reads Box (~3 Box AI calls)
```

Have Box open in a browser tab on the **reports** folder for step 4.

## The 3 contracts in Box

| Contract | Customer | Region | Quarter | Hardware | TCV | Promised | Actual |
|---|---|---|---|---|---|---|---|
| CTR-0001 | Tailspin Logistics | US-East (Ashburn, VA) | Q3 | none | $84.6K | 47 | 52 |
| CTR-0002 | Woodgrove Bank | EU-West (Dublin, IE) | Q2 | Meridian Systems | $1.63M | 92 | 111 |
| CTR-0003 | Contoso Manufacturing | APAC (Singapore) | Q4 | none | $21.6K | 38 | 38 |

## Script

### 1. Show what's in Box

> What deal history do you have?

Lists the 3 contracts. Shows the agent is reading real documents in Box.

### 2. The main moment: an unrealistic promise 🔴

> I'm closing a deal with a bank in Dublin, signing in Q4. 6 GPU racks from
> Meridian Systems plus 300 Core seats. I told them 80 days. Is that realistic?

Expected: 🔴 **RED, "80 days promised, history says 111."** Cites
**CTR-0002** (a similar Meridian deal that promised 92 days and took 111).
Three HIGH risks: the timeline, Q4 hardware delays, and Meridian's backorder
history.

### 3. The rep adjusts the promise 🟢

> OK, what if I promise 115 days instead?

Expected: 🟢 **GREEN, "115 days promised, history says 111."** Still warns
about Meridian. Shows the agent remembers the deal across messages.

### 4. Send it to the deal desk

> Save the report and send it to the deal desk.

Uploads the risk report PDF to the Box **reports** folder and creates a review
task. Switch to the Box tab and show both.

### 5. A small miss is still caught (optional) 🔴

> Different deal: 70 Core seats, Ashburn, Q3, promising 50 days.

Expected: 🔴 **RED, "50 days promised, history says 52."** Cites **CTR-0001**.
Promising 55 days gives 🟢 GREEN.

### 6. It doesn't make up numbers ⚪ (optional)

> How about 50 seats in Sydney, Q1, 45 days?

Expected: ⚪ **UNKNOWN**. There's no Sydney history, so it says so instead of
guessing.

## Tips

- **Give quantities and the vendor explicitly** ("6 GPU racks", "Meridian
  Systems"). A past deal only counts as comparable if it shares the region or
  vendor **and** is within ±40% of the deal's value (`RULES.md`), so a vague
  "some GPUs" might match nothing.
- **Re-saving is safe:** saving the report again uploads a new version of the
  PDF in Box.
- **If a judge asks why one comparable is enough:** with 3 contracts, each
  verdict is backed by a single deal. More contracts in Box make it more
  confident. With all 100 uploaded, the Ashburn / Q4 / Meridian deal comes back
  "55 days promised, history says 139," backed by CTR-0010, CTR-0050 and
  CTR-0013.
