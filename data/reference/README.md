# Reference data

`districts_2011.csv` — district → state list (640 districts) from DataMeet India community,
`datameet/maps` `Districts/Census_2011/2011_Dist.dbf`, derived from the Census of India 2011 Administrative Atlas.
Licence: Creative Commons Attribution 2.5 India (https://creativecommons.org/licenses/by/2.5/in/).
Attribution: "District list by DataMeet India community (CC BY 2.5 India), from Census of India 2011."
Used only to validate (state, district) pairs in `backend/app/pipeline/location.py`. It predates Telangana,
Ladakh and the Dadra & Nagar Haveli / Daman & Diu merger, so `location.py` treats those as their 2011 parents,
and it lacks districts created or renamed since 2011, which `location.py` recognises from the works data itself.
