# DEX Sentinel Dashboard: 5-Minute Walkthrough

## Overview (30 seconds)

This dashboard answers three simple questions:
1. **What's wrong?** — Why are employees frustrated?
2. **What matters most?** — Which issues should we fix first?
3. **Did it work?** — How much did the fix actually help?

The dashboard has **7 main sections**. We'll walk through the most important ones.

---

## Section 1: Command Center (Homepage) — 1 minute

**What you see**: A compelling headline, DEX Score, predictions, and a plan.

### The Headline
- **What it says**: "25 frustrated tickets are coming next week. Fixing 3 things saves $73K a year."
- **Why it matters**: One sentence tells the story: we know what's coming, we know what fixes it, we know the value
- **Scope**: "2,600 devices · 9,719 tickets · weeks 1-12"

### The Four Key Cards

**1. DEX Score (79.3/100)**
- **Simple meaning**: How satisfied are your employees with their digital experience?
- **What it combines**: Employee frustration + Device health + Whether fixes stick
- **Trend**: "Good · +7.6 pts · by department →" (shows it's improving)
- **At a glance**: Green = good, red = needs attention

**2. Predicted - Week 13**
- **What it says**: "25 frustrated tickets expected"
- **Why it matters**: You can plan remediation *before* the tickets land
- **Based on**: ML forecast from past 4 weeks

**3. Annual Benefits Realised**
- **What it says**: "$993K/yr saved"
- **Breakdown**: Tickets $107K + Productivity $708K
- **Why it matters**: Not just "we fixed things"; we measured the money saved

**4. #1 Problem**
- **What it says**: "Network latency · 144 devices · 398 extra tickets"
- **Why it matters**: Shows the single biggest issue blocking your workforce

### The Experience Trend Chart
- **Two lines**: DEX Score (cyan, steady around 75–80) and Avg Frustration (orange, tracking inversely)
- **What to look for**: Are they converging? Trending up? Any drops after fixes?
- **Time range**: Weeks 1–12, so you can spot seasonal patterns

### The Plan
- **Current state**: DEX 79.3
- **If we fix top 3 issues**: DEX jumps to 83.4
- **Savings**: $73K/year
- **Prevented**: 483 tickets avoided per year
- **How we know**: "Projected from past fixes of the same type · hover for method"

### Top 3 Actions to Raise DEX
- **#1 Network**: +1.5 DEX improvement
- **#2 Performance**: +1.4 DEX improvement
- **#3 Hardware**: +1.2 DEX improvement
- **Why ranked this way**: Combination of how many people it affects, how much frustration it causes, and likelihood of fix success

### Top Bar Controls
- **Filters**: All departments, All device models, All work modes, Date range (From W1 to W12)
- **Copilot**: Click to open AI assistant
- **Analyst details**: Toggle to hide/show dense content
- **Theme**: Light/dark mode

---

## Section 2: Proactive Watchlist — 1 minute

**What you see**: ML predictions for who will be frustrated next week and why.

### The Forecast
- **What it says**: Probability each employee will raise a frustrated ticket
- **Based on**: Past 4 weeks of frustration + device health + telemetry patterns
- **Why it matters**: IT can be proactive (update devices, roll out fixes) instead of reactive (wait for complaint, then fix)

### When Analyst Mode ON
- See: Calibration charts, ROC curves, model confidence
- Understand: How the model was trained and validated

---

## Section 3: Diagnose — 1.5 minutes

**What you see**: Paste or pick a ticket. Get a diagnosis in seconds.

### The Diagnosis Output

**Priority Score (0–100)**
- Combines: Frustration + Business Impact boost + Urgency boost + Device temperature
- Example: "Base frustration 70 + high impact +10 + urgent +10 + device overheating +5 = Priority 95 (P1)"
- **Why it matters**: Shows IT: "This isn't just a complaint, it's a business crisis"

**Root Cause (ranked)**
- Example: "Boot slowness (65% confidence) + RAM shortage (45% confidence)"
- Based on: What the employee said + what the device is doing
- **Why it matters**: Tells IT what to actually fix, not just which app to restart

**Evidence**
- Device: "This device crashed 3 times in the last 2 weeks"
- Person: "They've contacted IT 4 times about Outlook"
- **Why it matters**: Explains why we ranked it this way

**The Fix Recommendation**
- Example: "Update Outlook, then monitor for crashes"
- From: Our knowledge base of 22 playbooks
- Suggested by: Claude Copilot (AI assistant)

---

## Section 4: Software Remediation — 1 minute

**What you see**: Automated security fixes for vulnerable software versions.

### The Flow
1. **Security team sends an email** with version to remove (e.g., "Outlook 2019.1 has CVE-2024-xxxx")
2. **DEX Sentinel finds devices** with that exact version
3. **Safety check**: Blocks system-critical, shows dependencies
4. **Show plan**: "Remove from 47 devices, can't touch 3 (system-critical)"
5. **Execute with approval**: One-click, audit trail, rollback on error

### Why it matters
- **Speed**: Minutes instead of weeks of manual ticket routing
- **Safety**: Knows what breaks if we remove it
- **Traceability**: Complete audit trail for compliance

---

## Section 5: Proof & Value — 1 minute

**What you see**: Before/after numbers and a list of fixes that worked.

### Annual Benefits Realised
- **Savings**: $993K/yr ($107K tickets + $708K productivity)
- **Basis**: Real fixes applied to real devices, measured over time

### The Plan
- **Current DEX**: 79.3
- **If top 3 fixes applied**: 83.4 (+4.1 improvement)
- **Savings**: $73K/year
- **Prevented**: 483 tickets avoided per year
- **How we know**: "Projected from past fixes of the same type"

### Causal Outcomes (when analyst mode ON)
- **Before the fix**: This cohort averaged frustration 65
- **After the fix**: This cohort dropped to frustration 47
- **Did the fix cause it?**: We compare to a "matched group" that *didn't* get the fix
  - Matched group: also dropped from 65 → 54 (normal drift)
  - Fix group: dropped 65 → 47 (extra 18 points from the fix)
  - **Honest outcome**: The fix caused a 18-point improvement, not 18

---

## Section 6: Evidence — 30 seconds (if time)

**What you see**: The raw data behind our score.

### Available when analyst mode ON
- **DEX Score Breakdown**: All 5 components and their weights
- **Device Telemetry**: Boot times, crashes, temperature, battery health
- **Correlation Analysis**: Device health vs employee sentiment (proof they're linked)
- **Experience Details**: Frustration by week, repeat contacts, sentiment trends

---

## The Analyst Mode Toggle (always visible, top-right)

**What it does**: Shows/hides the "deep dive" content

### When OFF (default, jury view)
- Simple, clear, executive-friendly
- Just: The headline, 4 key cards, trend chart, the plan, top 3 actions
- No: Formulas, calibration charts, heatmaps, audit trails

### When ON (analyst view)
- Everything: All charts, all metrics, all assumptions
- Formulas shown so you can verify them
- Calibration curves so you can see model confidence

**Why we built it**: Same app for the jury (simple) and technical teams (deep).

---

## Five Insights You Should Leave With

1. **One headline tells the whole story**
   - "25 frustrated tickets are coming next week. Fixing 3 things saves $73K a year."
   - Not: "Avg frustration is 64 and rising, let's discuss strategy." 
   - But: "Here's what's coming, here's how to stop it, here's the money we save."

2. **Priority is mathematical, not gut-feel**
   - Top 3 actions ranked by: Impact (how many people) + Urgency (how time-sensitive) + Device health
   - IT can defend: "Network latency is #1 because 144 devices are affected, 398 extra tickets, and it cascades."

3. **Prediction enables prevention**
   - "25 frustrated tickets next week" means IT can proactively update devices, roll out fixes, notify teams
   - Not reactive: wait for complaint, then scramble

4. **Outcomes are honest and measured**
   - "Fix group improved by 18; matched control improved by 4; fix caused 14-point gain" 
   - Not inflated: "We fixed Outlook and frustration dropped by 18 points" (ignores natural drift)

5. **Same app, two audiences**
   - Jury sees: Headline, 4 cards, trend, plan, top 3 actions
   - Analysts see: All the charts, formulas, calibration curves, audit trails
   - One platform, two views

---

## Demo Script: 2-Minute Live Walk

**Start at Command Center** (30 seconds)
- "The headline tells the story: 25 frustrated tickets are coming next week; fixing 3 things saves $73K/year."
- "Look at the 4 cards: DEX Score 79.3 (good, improving), Next week 25 tickets, $993K/yr savings, #1 problem is network latency."
- "The trend shows DEX and frustration moving together; if we fix the top 3 things, we jump to 83.4."

**Scroll down to Top 3 Actions** (20 seconds)
- "#1 Network (+1.5 DEX): 144 devices, 398 extra tickets. If we upgrade NICs, boots get faster."
- "#2 Performance (+1.4 DEX): RAM upgrades, fewer hangs."
- "#3 Hardware (+1.2 DEX): Battery replacements, device stability."
- "Each one has a projected improvement based on similar fixes in the past."

**Click Diagnose tab** (30 seconds)
- "Paste a ticket: 'Outlook keeps crashing, I'm losing work, and I don't have time to call IT again.'"
- "Output shows:"
  - Frustration: 82 (angry)
  - Impact: High (losing work = blocking)
  - Urgency: High (repeat contact = they've asked before)
  - Priority: P1 (base 82 + impact boost + urgency boost)
  - Root cause: Outlook memory leak, boot slowness
  - Fix: Update Outlook, upgrade RAM, monitor for crashes

**Click Proof & Value** (20 seconds)
- "Annual benefits: $993K/yr. Breakdown: $107K from fewer tickets, $708K from productivity time saved."
- "Last month's Outlook update: applied to 140 devices, frustration dropped 21 points on avg."
- "Matched control dropped 6 points (normal drift), so the fix caused a 15-point gain."

**Closing** (10 seconds)
- "This is the full loop: Predict frustration → Diagnose the cause → Apply fix → Measure the impact → Show the ROI."

---

## Three Questions Jury Will Ask

**Q1: "Is this accurate?"**
- A: "Frustration scoring is 93.3% validated against domain experts on 9,597 real tickets. Dimensions are rule-based cues (e.g., 'can't work' = high impact), not black-box ML. Every score shows which phrases triggered it. You can verify."

**Q2: "How do you prioritize fairly?"**
- A: "Not gut-feel. We measure impact (how many people hurt), urgency (deadlines, escalations, repeats), and device health. Top 3 actions have the biggest combined impact on DEX."

**Q3: "How do you prove the fix worked?"**
- A: "Causal measurement. We compare fix cohort to matched control group. If both groups improve 10 points naturally, but fix group improves 25 points, the fix caused 15 points. No inflated claims."

---

## Key Takeaway

**"DEX Sentinel closes the loop: Predict what will frustrate employees next week, diagnose why, fix it with confidence, measure the impact, and show the ROI."**

