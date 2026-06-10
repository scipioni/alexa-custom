from alexa_custom.number_parser import parse_percentage


class TestParsePercentage:
    def test_digit_with_percent_sign(self):
        assert parse_percentage("volume al 80%") == 0.80

    def test_digit_with_per_cento(self):
        assert parse_percentage("50 per cento") == 0.50

    def test_standalone_digit(self):
        assert parse_percentage("metti volume a 50") == 0.50

    def test_italian_number_word(self):
        assert parse_percentage("ottanta") == 0.80

    def test_italian_compound_word(self):
        assert parse_percentage("venticinque") == 0.25

    def test_value_clamped_at_max(self):
        assert parse_percentage("cento cinquanta per cento") == 1.0

    def test_value_clamped_at_min(self):
        assert parse_percentage("zero") == 0.0

    def test_no_number_in_transcript(self):
        assert parse_percentage("alza il volume") is None

    def test_empty_transcript(self):
        assert parse_percentage("") is None

    def test_units(self):
        assert parse_percentage("uno") == 0.01
        assert parse_percentage("due") == 0.02
        assert parse_percentage("tre") == 0.03
        assert parse_percentage("dieci") == 0.10
        assert parse_percentage("cento") == 1.0

    def test_compound_edge_cases(self):
        assert parse_percentage("ventuno") == 0.21
        assert parse_percentage("ventotto") == 0.28
        assert parse_percentage("trentatré") == 0.33
        assert parse_percentage("novantanove") == 0.99

    def test_digit_above_100_clamped(self):
        assert parse_percentage("200%") == 1.0

    def test_with_full_phrase(self):
        assert parse_percentage("ehi assistente volume al 80%") == 0.80
        assert parse_percentage("metti il volume a settanta") == 0.70

    def test_diacritics_stripped(self):
        assert parse_percentage("sessantatré") == 0.63
        assert parse_percentage("ventitré") == 0.23

    def test_cento_with_per_cento_not_double_counted(self):
        result = parse_percentage("cento per cento")
        assert result == 1.0

    def test_multiple_digits_picks_first(self):
        assert parse_percentage("50 80") == 0.50

    def test_digit_with_spaces_before_percent(self):
        assert parse_percentage("50 %") == 0.50
