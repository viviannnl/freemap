"""Reading Craigslist Vancouver.

    sapi      the internal search endpoint, and how to decode its items
    free      the free section ("zip") - glyphs, photos, no prices
    rentals   apartments/housing ("apa") - price, bedrooms, walking distance
    posted    the true post time for one posting (the search API has none)
    building  how old a building is, from the posting or city open data

Every module here is read-only and stateless: it fetches, decodes and returns.
Filtering, freshness and anything that needs to remember a previous visit is the
browser's job, which is what lets the whole app deploy as serverless functions.
"""
