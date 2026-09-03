-- Чистит накопленный мусор от pytest: тесты_fact_crud веками оставляли факты,
-- а крон-фактчек (`src/cronjob/fact/fact_verify.py`) каждый час гонял их через
-- реальный LLM (`fact_verifier`, workflow `fact_verify`) — см. баг #35981.
-- Правка в тестах оставила новые строки; эти — последние от старых прогонов.
DELETE FROM `fact` WHERE `document` = '__pytest_test_fact_document__';
