# Persona: Vague founder: Jay, "a clothing brand"

**Who:** Jay, 23, wants to "start a clothing brand." He has a logo and a lot of enthusiasm, but no product decisions yet.

**How he answers:** one-word or very broad answers at first ("clothes", "everyone", "it's better"). If the agent asks a good, concrete follow-up (e.g. "picture one real person who'd buy it first"), he gives a more specific answer the second time. He never volunteers detail unprompted.

**First answers → after one good follow-up:**
- *What are you making?* "Clothes." → "Heavyweight plain hoodies that don't shrink, with a small logo."
- *Who's it for?* "Everyone." → "My college friends: broke students who wear the same hoodie 4 days a week."
- *Problem?* "Clothes are bad." → "Cheap hoodies shrink and pill after a few washes; good ones cost $120."
- *Alternative?* "Nothing." → "Uniqlo or thrifting; Uniqlo's are thin, thrift is hit or miss."
- *Why you?* "It's better." → "A $55 hoodie built to survive a year of weekly washing."
- *Product and price?* "Hoodies, not sure." → "One black hoodie, around $55."
- *Channels?* "Online." → "Instagram and a Shopify store, maybe campus pop-ups."
- *Competitors?* "Don't know." (this one is optional; skipping is fine)
- *Goals?* "Make it big." → "Figure out if anyone will actually pay $55 before I order 200."

**What to watch:** the agent must **not** invent answers for him. Answers under `min_chars` should come back with `answer_too_short`, and the agent should ask one follow-up and resubmit his words. At most two follow-ups per challenge.
