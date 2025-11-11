# Commute_Grapher
A simple cron job to log commute times, and display the logged durations with a simple flask app.

## Configure your .env file
Update the `example.env` file with your Google Projects proper APIs
Your API key will need access to Geocoding, Routes, and Directions(Possibly Not Directions...)
Probably need to enable billing as well, however I dont believe there should be much costs associated with these API calls.

## Run it
`docker-compose up`
Verify the build is successful.

Cron job only runs during configured "Work" Times that will need to be updated in the `fetcher/routes_fetch_travel_time.py` `choose_direction()` function
https://github.com/Benerman/Commute_Grapher/blob/master/fetcher/routes_fetch_travel_time.py#L167