# Standardized Otaku Test Bootstrap
import os
import sys
import json
import re

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_TESTS_DIR = os.path.abspath(os.path.join(_TEST_DIR, '..'))
_REPO_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import conftest  # Centralized Kodi mock harness  # noqa: F401

import unittest
from resources.lib.ui import control, source_utils
from resources.lib.pages import Sources


class TestMilestone3AdversarialChallenger(unittest.TestCase):
    """
    Adversarial stress-testing suite for Milestone 3 Remediation:
    1. Sequel isolation (e.g. Piano no Mori Season 2 vs Piano no Mori <= 40).
    2. Short title isolation ('Monster', 'K', 'C', 'Nana', 'Bleach', 'Air', 'FLCL').
    3. Complex titles, punctuation, and release formats.
    4. Full parametric dataset evaluation across all 576 anime entries.
    """

    @classmethod
    def setUpClass(cls):
        fixture_path = os.path.join(_TESTS_DIR, 'fixtures', 'comprehensive_anime_dataset.json')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            cls.dataset = json.load(f)

    def test_sequel_isolation_piano_no_mori_and_franchises(self):
        """
        Adversarially verify that sequels, second seasons, and later parts
        score <= 40 when evaluated against Season 1 / base query.
        """
        # Piano no Mori with and without aliases
        aliases_piano = ['Forest of Piano', 'Piano no Mori (TV)', 'Forest of Piano (Movie)']
        piano_sequels = [
            'Piano no Mori Season 2',
            'Piano no Mori Season 02',
            'Piano no Mori Season 3',
            'Piano no Mori S2',
            'Piano no Mori S02',
            'Piano no Mori S3',
            'Piano no Mori 2nd Season',
            'Piano no Mori 3rd Season',
            'Piano no Mori Second Season',
            'Piano no Mori Third Season',
            'Piano no Mori Part 2',
            'Piano no Mori Part 3',
            'Piano no Mori Cour 2',
            'Piano no Mori 2nd Cour',
            'Piano no Mori II',
            'Piano no Mori III',
            'Piano no Mori 2',
            'Piano no Mori 3',
            'Forest of Piano Season 2',
            'Forest of Piano S2',
            'Forest of Piano 2nd Season',
            '[HorribleSubs] Piano no Mori Season 2 - 01 [720p].mkv',
            '[SubsPlease] Piano no Mori S2 - 01 [1080p].mkv',
            '[Erai-raws] Piano no Mori 2nd Season - 01 [1080p].mkv',
            '[Judas] Piano no Mori Part 2 - 01 [1080p].mkv',
        ]

        for cand in piano_sequels:
            score = source_utils.score_title_candidate('Piano no Mori', cand, aliases=aliases_piano)
            self.assertLessEqual(
                score, 40,
                f"Sequel leak! Candidate '{cand}' scored {score} (> 40) against 'Piano no Mori'"
            )

        # 20 Popular Multi-Season Franchises
        franchise_cases = [
            ('Shingeki no Kyojin', ['Shingeki no Kyojin Season 2', 'Shingeki no Kyojin Season 3', 'Shingeki no Kyojin The Final Season']),
            ('Boku no Hero Academia', ['Boku no Hero Academia 2nd Season', 'Boku no Hero Academia 3rd Season', 'Boku no Hero Academia 4th Season', 'Boku no Hero Academia 5th Season']),
            ('Mob Psycho 100', ['Mob Psycho 100 II', 'Mob Psycho 100 III']),
            ('One Punch Man', ['One Punch Man 2nd Season', 'One Punch Man Season 2', 'One Punch Man S2']),
            ('Jujutsu Kaisen', ['Jujutsu Kaisen 2nd Season', 'Jujutsu Kaisen Season 2']),
            ('Vinland Saga', ['Vinland Saga Season 2', 'Vinland Saga S2']),
            ('Re:Zero kara Hajimeru Isekai Seikatsu', ['Re:Zero kara Hajimeru Isekai Seikatsu 2nd Season']),
            ('Spy x Family', ['Spy x Family Season 2', 'Spy x Family Part 2']),
            ('Mushoku Tensei: Isekai Ittara Honki Dasu', ['Mushoku Tensei: Isekai Ittara Honki Dasu Season 2', 'Mushoku Tensei II: Isekai Ittara Honki Dasu']),
            ('Kimetsu no Yaiba', ['Kimetsu no Yaiba: Yuukaku-hen', 'Kimetsu no Yaiba: Katanakaji no Sato-hen']),
            ('Dr. Stone', ['Dr. Stone: Stone Wars', 'Dr. Stone: New World']),
            ('The Promised Neverland', ['The Promised Neverland Season 2']),
            ('Tate no Yuusha no Nariagari', ['Tate no Yuusha no Nariagari Season 2', 'Tate no Yuusha no Nariagari Season 3']),
            ('Kono Subarashii Sekai ni Shukufuku wo!', ['Kono Subarashii Sekai ni Shukufuku wo! 2', 'Kono Subarashii Sekai ni Shukufuku wo! 3']),
            ('Overlord', ['Overlord II', 'Overlord III', 'Overlord IV']),
            ('Code Geass: Hangyaku no Lelouch', ['Code Geass: Hangyaku no Lelouch R2']),
            ('Steins;Gate', ['Steins;Gate 0', 'Steins Gate 0']),
            ('Sword Art Online', ['Sword Art Online II', 'Sword Art Online: Alicization']),
            ('Noragami', ['Noragami Aragoto']),
            ('Psycho-Pass', ['Psycho-Pass 2', 'Psycho-Pass 3']),
        ]

        for target, sequels in franchise_cases:
            for seq in sequels:
                score = source_utils.score_title_candidate(target, seq)
                self.assertLessEqual(
                    score, 40,
                    f"Sequel leak! Candidate '{seq}' scored {score} (> 40) against '{target}'"
                )

    def test_short_titles_isolation_all_seven(self):
        """
        Adversarially verify that all 7 short-titled anime ('Monster', 'K', 'C', 'Nana',
        'Bleach', 'Air', 'FLCL') reject derivative series, episode traps, and substrings.
        """
        short_title_matrix = {
            'Monster': {
                'aliases': ["Naoki Urasawa's Monster"],
                'year': 2004,
                'derivatives': [
                    'Re:Monster', 'Monster Musume no Iru Nichijou', 'Monster Hunter Stories',
                    'Pocket Monsters', 'Monster Rancher', 'Monster Strike', 'The Monster Within',
                    'Attack on Titan - 05 - The Roar of the Monster.mkv',
                    'Show Name - S01E05 - The Monster Within.mkv'
                ],
                'valid': '[ASW] Monster - 01 [BD 1080p].mkv'
            },
            'K': {
                'aliases': ['K-Project', 'K Project'],
                'year': 2012,
                'derivatives': [
                    'K-On!', 'Special A', 'Kill la Kill', 'Re:K', 'K Musume',
                    'K: Return of Kings', 'K: Missing Kings',
                    'Unrelated Show - 01 - The K Within.mkv'
                ],
                'valid': '[Coalgirls] K - 01 [1080p].mkv'
            },
            'C': {
                'aliases': ['C: The Money of Soul and Possibility Control', 'Control'],
                'year': 2011,
                'derivatives': [
                    'Code Geass', 'Generic release codecs (AVC/HEVC)', 'Re:C', 'C Musume',
                    'Gundam 00 - 01 [x264 1080p AAC].mkv',
                    'Unrelated Show - 01 - The C Within.mkv'
                ],
                'valid': '[SubsPlease] C - 01 (1080p).mkv'
            },
            'Nana': {
                'aliases': [],
                'year': 2006,
                'derivatives': [
                    'Munou na Nana', 'Talentless Nana', 'Nanatsu no Taizai', 'Banana Fish',
                    'Nana (2005 Live Action)', 'Re:Nana', 'Nana Musume',
                    'Unrelated Show - 01 - The Nana Within.mkv'
                ],
                'valid': '[SubsPlease] Nana - 01 (1080p).mkv'
            },
            'Bleach': {
                'aliases': ['Burichi'],
                'year': 2004,
                'derivatives': [
                    'Bleach: Sennen Kessen-hen', 'Bleach: Thousand-Year Blood War',
                    'Burn the Witch', 'Bleach: Memories of Nobody', 'Re:Bleach', 'Bleach Musume',
                    'House Cleaning - 01 - Pass the Bleach.mkv'
                ],
                'valid': '[SubsPlease] Bleach - 01 (1080p).mkv'
            },
            'Air': {
                'aliases': ['Ea'],
                'year': 2005,
                'derivatives': [
                    'Air Gear', 'Avatar: The Last Airbender', 'Air Master', 'Re:Air', 'Air Musume',
                    'Fairy Tail', 'Prince of Tennis - S01E03 - High in the Air.mkv',
                    'Unrelated Show - 01 - The Air Within.mkv'
                ],
                'valid': '[Exiled-Destiny] Air - 01 (1080p).mkv'
            },
            'FLCL': {
                'aliases': ['Fooly Cooly'],
                'year': 2000,
                'derivatives': [
                    'FLCL Progressive', 'FLCL Alternative', 'FLCL Grunge', 'FLCL Shoegaze',
                    'Re:FLCL', 'FLCL Musume', 'Unrelated Show - 01 - The FLCL Within.mkv'
                ],
                'valid': '[SubsPlease] FLCL - 01 (1080p).mkv'
            }
        }

        for title, spec in short_title_matrix.items():
            aliases = spec['aliases']
            year = spec['year']

            # 1. Valid exact release must score >= 140
            valid_score = source_utils.score_title_candidate(title, spec['valid'], aliases=aliases, year=year)
            self.assertGreaterEqual(
                valid_score, 140,
                f"Valid release '{spec['valid']}' scored {valid_score} (< 140) for '{title}'"
            )

            # 2. Release descriptors must score >= 110
            for desc in [f'{title} (Dub)', f'{title} (Sub)', f'{title} (TV)']:
                desc_score = source_utils.score_title_candidate(title, desc, aliases=aliases, year=year)
                self.assertGreaterEqual(
                    desc_score, 110,
                    f"Descriptor release '{desc}' scored {desc_score} (< 110) for '{title}'"
                )

            # 3. All derivatives and episode traps must score <= 40
            for deriv in spec['derivatives']:
                score = source_utils.score_title_candidate(title, deriv, aliases=aliases, year=year)
                self.assertLessEqual(
                    score, 40,
                    f"False positive! Derivative '{deriv}' scored {score} (> 40) for '{title}'"
                )

            # 4. Fuzzy match must isolate the valid release as index 0
            file_candidates = [spec['valid']] + spec['derivatives'][:4]
            fuzzy_results = source_utils.get_fuzzy_match(title, file_candidates)
            self.assertEqual(
                fuzzy_results, [0],
                f"Fuzzy match failed for '{title}': expected [0] but got {fuzzy_results}"
            )

            # 5. filter_sources must drop all derivatives
            torrents = [
                {'name': spec['valid'], 'hash': 'HASH_VALID', 'seeds': 100},
            ]
            for i, d in enumerate(spec['derivatives']):
                torrents.append({'name': d, 'hash': f'HASH_DIST_{i}', 'seeds': 50})

            filtered = source_utils.filter_sources(
                'nyaa', torrents, mal_id=1, season=1, episode=1, show_title=title, aliases=aliases
            )
            self.assertEqual(
                len(filtered), 1,
                f"filter_sources leaked derivatives for '{title}': kept {len(filtered)} items instead of 1"
            )
            self.assertEqual(filtered[0]['name'], spec['valid'])
            self.assertGreaterEqual(filtered[0]['relevance'], 140)

    def test_complex_titles_punctuation_and_scene_formats(self):
        """
        Adversarially verify complex titles, punctuation normalization,
        bracketed metadata, and diverse scene/fansub release formats.
        """
        test_cases = [
            # Semicolons and colons
            ('Steins;Gate', 'Steins Gate - 01 [1080p].mkv', 140),
            ('Steins;Gate', '[SubsPlease] Steins;Gate - 01 (1080p).mkv', 140),
            ('Fate/Zero', 'Fate Zero - 01.mkv', 140),
            ('Fate/Zero', '[Commie] Fate/Zero - 01 [BD 1080p].mkv', 140),
            ('D.Gray-man', 'D Gray-man - 01.mkv', 140),
            ('D.Gray-man', '[Coalgirls] D.Gray-man - 01 [720p].mkv', 140),
            ('Tokyo Ghoul:re', 'Tokyo Ghoul re - 01.mkv', 140),
            ('Fullmetal Alchemist: Brotherhood', '[Erai-raws] Fullmetal Alchemist - Brotherhood - 01 [1080p].mkv', 140),
            # Numbers as titles
            ('86', '[SubsPlease] 86 - 01 (1080p).mkv', 140),
            ('91 Days', '[HorribleSubs] 91 Days - 01 [720p].mkv', 140),
            ('Mob Psycho 100', '[Erai-raws] Mob Psycho 100 - 01 [1080p].mkv', 140),
            # Scene formats
            ('Monster', 'Monster.S01E01.1080p.BluRay.x264.mkv', 140),
            ('Monster', 'Monster.E01.1080p.mkv', 140),
            ('Monster', 'Monster.01.1080p.mkv', 140),
            ('Monster', 'Monster 01 (1080p).mkv', 140),
            ('Monster', '[Beatrice-Raws] Monster 01 [BDRip 1920x1080 HEVC TrueHD].mkv', 140),
        ]

        for query, candidate, min_score in test_cases:
            score = source_utils.score_title_candidate(query, candidate)
            self.assertGreaterEqual(
                score, min_score,
                f"Candidate '{candidate}' scored {score} (< {min_score}) against '{query}'"
            )

    def test_parametric_evaluation_576_entries(self):
        """
        Adversarially evaluate all 576 entries in comprehensive_anime_dataset.json:
        - Exact self-match >= 140
        - Release descriptor match >= 110
        - Listed aliases >= 115
        - All distractors <= 40
        Verify 0 false positives and 0 false negatives across thousands of candidate pairs.
        """
        tp = 0
        tn = 0
        fp = 0
        fn = 0

        fp_violations = []
        fn_violations = []

        for entry in self.dataset:
            title = entry['title']
            aliases = entry.get('aliases', [])
            year = entry.get('year')
            distractors = entry.get('distractors', [])

            # 1. Canonical self-match
            s_self = source_utils.score_title_candidate(title, title, aliases=aliases, year=year)
            if s_self >= 140:
                tp += 1
            else:
                fn += 1
                fn_violations.append((title, title, s_self, 'self-match < 140'))

            # 2. Release descriptor match
            desc_cand = f"{title} (Dub)"
            s_desc = source_utils.score_title_candidate(title, desc_cand, aliases=aliases, year=year)
            if s_desc >= 110:
                tp += 1
            else:
                fn += 1
                fn_violations.append((title, desc_cand, s_desc, 'descriptor match < 110'))

            # 3. Alias matches
            for alias in aliases:
                s_alias = source_utils.score_title_candidate(title, alias, aliases=aliases, year=year)
                if s_alias >= 115:
                    tp += 1
                else:
                    fn += 1
                    fn_violations.append((title, alias, s_alias, 'alias match < 115'))

            # 4. Distractors
            for dist in distractors:
                s_dist = source_utils.score_title_candidate(title, dist, aliases=aliases, year=year)
                if s_dist <= 40:
                    tn += 1
                else:
                    fp += 1
                    fp_violations.append((title, dist, s_dist, 'distractor > 40'))

        total_pos = tp + fn
        total_neg = tn + fp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / total_pos if total_pos > 0 else 0.0
        accuracy = (tp + tn) / (total_pos + total_neg) if (total_pos + total_neg) > 0 else 0.0
        specificity = tn / total_neg if total_neg > 0 else 0.0

        self.assertEqual(len(fp_violations), 0, f"False Positives found: {fp_violations}")
        self.assertEqual(len(fn_violations), 0, f"False Negatives found: {fn_violations}")
        self.assertEqual(precision, 1.0, f"Precision is {precision} (expected 1.0)")
        self.assertEqual(recall, 1.0, f"Recall is {recall} (expected 1.0)")
        self.assertEqual(accuracy, 1.0, f"Accuracy is {accuracy} (expected 1.0)")
        self.assertEqual(specificity, 1.0, f"Specificity is {specificity} (expected 1.0)")


if __name__ == '__main__':
    unittest.main()
