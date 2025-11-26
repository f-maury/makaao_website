# Not included in this repository
For licensing reasons, some files that you would need to make the website work are not included here. These are:
   - `website/data/LOINC_*.ttl`
   - `website/data/makaao_core.csv`
   - `website/data/makaao_v*.rdf`
   - `db/aab_*.html`
   - `db/slug_map.json`
# Installation
1. If you want to run the scripts on your own, you need a Python 3.11 environment. Other Python versions may or may not work, but there is no guarantee.
2. Clone the repository on you local machine:
   ```bash
   git clone https://github.com/f-maury/MAKAAO_website
   ```
3. Navigate to the repository, and install required packages:
   ```bash
   pip install -r requirements.txt
   ```
4. To initialize container:
   ```bash
   docker-compose up -d
   ```
5. To turn off and restart:
   ```bash
   docker-compose stop
   docker-compose start
   ```
6. To remove container and its data:
   ```bash
   docker-compose down -v
   ```
