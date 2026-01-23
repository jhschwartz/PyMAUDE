"""
Tests for analysis_helpers module.

Includes both unit tests with synthetic data and integration tests with real test database.
"""

import pytest
import pandas as pd
import os
import tempfile
from pymaude import MaudeDatabase
from pymaude import analysis_helpers


class TestAnalysisHelpers:
    """Unit tests with synthetic data."""

    def test_trends_for(self):
        """Test yearly trends calculation."""
        df = pd.DataFrame({
            'DATE_RECEIVED': ['2020-01-15', '2020-06-20', '2021-03-10', '2021-08-05', '2021-12-25'],
            'EVENT_TYPE': ['Death', 'Injury', 'Malfunction', 'Death', 'Injury']
        })

        trends = analysis_helpers.trends_for(df)

        assert len(trends) == 2  # 2020 and 2021
        assert trends['year'].tolist() == [2020, 2021]
        assert trends.loc[trends['year'] == 2020, 'event_count'].values[0] == 2
        assert trends.loc[trends['year'] == 2021, 'event_count'].values[0] == 3
        assert trends.loc[trends['year'] == 2020, 'deaths'].values[0] == 1
        assert trends.loc[trends['year'] == 2021, 'deaths'].values[0] == 1

    def test_trends_for_missing_columns(self):
        """Test trends_for with missing columns raises error."""
        df = pd.DataFrame({'DATE_RECEIVED': ['2020-01-15']})

        with pytest.raises(ValueError, match="missing required columns"):
            analysis_helpers.trends_for(df)

    def test_event_type_breakdown_for(self):
        """Test event type breakdown."""
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5],
            'EVENT_TYPE': ['Death', 'Injury', 'Malfunction', 'Death', 'Injury, Malfunction']
        })

        breakdown = analysis_helpers.event_type_breakdown_for(df)

        assert breakdown['total'] == 5
        assert breakdown['deaths'] == 2
        assert breakdown['injuries'] == 2
        assert breakdown['malfunctions'] >= 2  # At least 2

    def test_event_type_breakdown_deduplicates(self):
        """Test that event_type_breakdown deduplicates by MDR_REPORT_KEY."""
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 1, 2, 2, 3],  # Duplicates
            'EVENT_TYPE': ['Death', 'Death', 'Injury', 'Injury', 'Malfunction']
        })

        breakdown = analysis_helpers.event_type_breakdown_for(df)

        assert breakdown['total'] == 3  # Only 3 unique reports
        assert breakdown['deaths'] == 1
        assert breakdown['injuries'] == 1
        assert breakdown['malfunctions'] == 1

    def test_top_manufacturers_for(self):
        """Test top manufacturers calculation."""
        df = pd.DataFrame({
            'MANUFACTURER_D_NAME': ['Acme Corp', 'Acme Corp', 'Beta Inc', 'Gamma LLC', 'Beta Inc']
        })

        top_mfg = analysis_helpers.top_manufacturers_for(df, n=2)

        assert len(top_mfg) == 2
        assert top_mfg.iloc[0]['manufacturer'] in ['Acme Corp', 'Beta Inc']
        assert top_mfg.iloc[0]['event_count'] == 2

    def test_date_range_summary_for(self):
        """Test date range summary."""
        df = pd.DataFrame({
            'DATE_RECEIVED': ['2020-01-01', '2020-06-15', '2020-12-31']
        })

        summary = analysis_helpers.date_range_summary_for(df)

        assert summary['first_date'] == '2020-01-01'
        assert summary['last_date'] == '2020-12-31'
        assert summary['total_days'] == 365  # 2020 was a leap year
        assert summary['total_records'] == 3

    def test_standardize_brand_names(self):
        """Test brand name standardization."""
        df = pd.DataFrame({
            'BRAND_NAME': ['VENOVO', 'Venovo Stent', 'vici device', 'Unknown Product', None]
        })
        mapping = {'venovo': 'Venovo', 'vici': 'Vici'}

        result = analysis_helpers.standardize_brand_names(df, mapping)

        assert 'standard_brand' in result.columns
        # Check non-null values
        assert result['standard_brand'].iloc[0] == 'Venovo'
        assert result['standard_brand'].iloc[1] == 'Venovo'
        assert result['standard_brand'].iloc[2] == 'Vici'
        assert result['standard_brand'].iloc[3] == 'Unknown Product'
        # Check null value (pandas converts None to NaN)
        assert pd.isna(result['standard_brand'].iloc[4])

    def test_standardize_brand_names_custom_columns(self):
        """Test brand name standardization with custom column names."""
        df = pd.DataFrame({
            'custom_brand': ['VENOVO Product', 'VICI Device']
        })
        mapping = {'venovo': 'Venovo', 'vici': 'Vici'}

        result = analysis_helpers.standardize_brand_names(
            df, mapping, source_col='custom_brand', target_col='cleaned_brand'
        )

        assert 'cleaned_brand' in result.columns
        assert result['cleaned_brand'].tolist() == ['Venovo', 'Vici']

    def test_hierarchical_brand_standardization_all_levels(self):
        """Test hierarchical standardization with all three levels."""
        df = pd.DataFrame({
            'BRAND_NAME': [
                'Inari Medical ClotTriever XL',
                'Inari Medical ClotTriever BOLD',
                'CLOTTRIEVER CATHETER',  # Should match family but not specific
                'FlowTriever System',
                'Some Unknown Device'
            ],
            'MANUFACTURER_D_NAME': [
                'Inari Medical ClotTriever',
                'Inari Medical ClotTriever',
                'Inari Medical ClotTriever',
                'Inari Medical FlowTriever',
                'Unknown Manufacturer'
            ]
        })

        specific = {
            'clottriever xl': 'Inari Medical ClotTriever XL',
            'clottriever bold': 'Inari Medical ClotTriever BOLD',
        }
        family = {
            'clottriever': 'Inari Medical ClotTriever (unspecified)',
            'flowtriever': 'Inari Medical FlowTriever (unspecified)',
        }
        manufacturer = {
            'clottriever': 'Inari Medical',
            'flowtriever': 'Inari Medical',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df,
            specific_mapping=specific,
            family_mapping=family,
            manufacturer_mapping=manufacturer
        )

        # Check columns exist
        assert 'device_model' in result.columns
        assert 'device_family' in result.columns
        assert 'manufacturer' in result.columns

        # Check specific matches
        assert result.iloc[0]['device_model'] == 'Inari Medical ClotTriever XL'
        assert result.iloc[1]['device_model'] == 'Inari Medical ClotTriever BOLD'

        # Check family match (no specific match)
        assert result.iloc[2]['device_model'] == 'Inari Medical ClotTriever (unspecified)'
        assert result.iloc[2]['device_family'] == 'Inari Medical ClotTriever (unspecified)'

        # Check FlowTriever
        assert result.iloc[3]['device_model'] == 'Inari Medical FlowTriever (unspecified)'
        assert result.iloc[3]['manufacturer'] == 'Inari Medical'

        # Check unmatched device
        assert pd.isna(result.iloc[4]['device_model'])
        assert pd.isna(result.iloc[4]['manufacturer'])

    def test_hierarchical_brand_standardization_specific_only(self):
        """Test hierarchical standardization with only specific mapping."""
        df = pd.DataFrame({
            'BRAND_NAME': ['ClotTriever XL', 'ClotTriever BOLD', 'ClotTriever']
        })

        specific = {
            'clottriever xl': 'Inari Medical ClotTriever XL',
            'clottriever bold': 'Inari Medical ClotTriever BOLD',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, specific_mapping=specific
        )

        # First two should match
        assert result.iloc[0]['device_model'] == 'Inari Medical ClotTriever XL'
        assert result.iloc[1]['device_model'] == 'Inari Medical ClotTriever BOLD'

        # Third should not match (no family mapping provided)
        assert pd.isna(result.iloc[2]['device_model'])

    def test_hierarchical_brand_standardization_manufacturer_only(self):
        """Test hierarchical standardization with only manufacturer mapping."""
        df = pd.DataFrame({
            'BRAND_NAME': ['ClotTriever XL', 'FlowTriever', 'Lightning Bolt'],
            'MANUFACTURER_D_NAME': ['Inari ClotTriever', 'Inari FlowTriever', 'Penumbra Lightning']
        })

        manufacturer = {
            'clottriever': 'Inari Medical',
            'flowtriever': 'Inari Medical',
            'lightning': 'Penumbra',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, manufacturer_mapping=manufacturer
        )

        # All should have manufacturers but no device models
        assert result.iloc[0]['manufacturer'] == 'Inari Medical'
        assert result.iloc[1]['manufacturer'] == 'Inari Medical'
        assert result.iloc[2]['manufacturer'] == 'Penumbra'
        assert all(pd.isna(result['device_model']))

    def test_hierarchical_brand_standardization_prevents_double_match(self):
        """Test that specific matches prevent family matches."""
        df = pd.DataFrame({
            'BRAND_NAME': ['Inari Medical ClotTriever XL Catheter']
        })

        # Both patterns would match, but specific should take precedence
        specific = {
            'clottriever xl': 'Inari Medical ClotTriever XL',
        }
        family = {
            'clottriever': 'Inari Medical ClotTriever (unspecified)',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df,
            specific_mapping=specific,
            family_mapping=family
        )

        # Should match specific, not family
        assert result.iloc[0]['device_model'] == 'Inari Medical ClotTriever XL'
        # Family should also be set since the brand name matches family pattern
        assert result.iloc[0]['device_family'] == 'Inari Medical ClotTriever (unspecified)'

    def test_hierarchical_brand_standardization_none_values(self):
        """Test hierarchical standardization handles None values."""
        df = pd.DataFrame({
            'BRAND_NAME': ['ClotTriever XL', None, 'FlowTriever']
        })

        specific = {
            'clottriever xl': 'Inari Medical ClotTriever XL',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, specific_mapping=specific
        )

        # None should remain unmatched
        assert pd.isna(result.iloc[1]['device_model'])
        assert pd.isna(result.iloc[1]['manufacturer'])

    def test_hierarchical_brand_standardization_case_insensitive(self):
        """Test that matching is case-insensitive."""
        df = pd.DataFrame({
            'BRAND_NAME': ['CLOTTRIEVER XL', 'ClotTriever BOLD', 'clottriever']
        })

        specific = {
            'clottriever xl': 'Inari Medical ClotTriever XL',
            'clottriever bold': 'Inari Medical ClotTriever BOLD',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, specific_mapping=specific
        )

        assert result.iloc[0]['device_model'] == 'Inari Medical ClotTriever XL'
        assert result.iloc[1]['device_model'] == 'Inari Medical ClotTriever BOLD'

    def test_hierarchical_brand_standardization_missing_column(self):
        """Test error when source column missing."""
        df = pd.DataFrame({'OTHER_COLUMN': ['Device A']})

        with pytest.raises(ValueError, match="must contain 'BRAND_NAME' column"):
            analysis_helpers.hierarchical_brand_standardization(df, manufacturer_mapping={})

    def test_hierarchical_brand_standardization_custom_source_col(self):
        """Test hierarchical standardization with custom source column."""
        df = pd.DataFrame({
            'custom_brand': ['ClotTriever XL', 'FlowTriever'],
            'MANUFACTURER_D_NAME': ['Inari ClotTriever', 'Inari FlowTriever']
        })

        manufacturer = {
            'clottriever': 'Inari Medical',
            'flowtriever': 'Inari Medical',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, manufacturer_mapping=manufacturer, source_col='custom_brand'
        )

        assert result.iloc[0]['manufacturer'] == 'Inari Medical'
        assert result.iloc[1]['manufacturer'] == 'Inari Medical'

    def test_hierarchical_brand_standardization_preserves_original(self):
        """Test that original BRAND_NAME column is preserved."""
        df = pd.DataFrame({
            'BRAND_NAME': ['ClotTriever XL Original Name']
        })

        specific = {
            'clottriever xl': 'Inari Medical ClotTriever XL',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, specific_mapping=specific
        )

        # Original should be preserved
        assert result['BRAND_NAME'].iloc[0] == 'ClotTriever XL Original Name'
        # But standardized version should be in device_model
        assert result['device_model'].iloc[0] == 'Inari Medical ClotTriever XL'

    def test_hierarchical_brand_standardization_order_matters(self):
        """Test that more specific patterns should be listed first in mappings."""
        df = pd.DataFrame({
            'BRAND_NAME': ['Lightning Bolt 7', 'Lightning Flash']
        })

        # If order matters, Lightning Bolt should match before Lightning
        family = {
            'lightning bolt': 'Penumbra Lightning Bolt (unspecified)',
            'lightning flash': 'Penumbra Lightning Flash (unspecified)',
            'lightning': 'Penumbra Lightning (unspecified)',
        }

        result = analysis_helpers.hierarchical_brand_standardization(
            df, family_mapping=family
        )

        # Should match the more specific patterns first
        assert result.iloc[0]['device_model'] == 'Penumbra Lightning Bolt (unspecified)'
        assert result.iloc[1]['device_model'] == 'Penumbra Lightning Flash (unspecified)'

    def test_summarize_by_brand(self):
        """Test brand summarization."""
        df = pd.DataFrame({
            'standard_brand': ['Brand A', 'Brand A', 'Brand B', 'Brand B', 'Brand C'],
            'DATE_RECEIVED': ['2020-01-01', '2020-06-01', '2020-03-01', '2020-09-01', '2021-01-01'],
            'EVENT_TYPE': ['Injury', 'Death', 'Malfunction', 'Injury', 'Death']
        })

        summary = analysis_helpers.summarize_by_brand(df)

        assert summary['counts'] == {'Brand A': 2, 'Brand B': 2, 'Brand C': 1}
        assert 'temporal' in summary
        assert 'event_types' in summary
        assert 'date_range' in summary

    def test_summarize_by_brand_missing_column(self):
        """Test summarize_by_brand with missing group column."""
        df = pd.DataFrame({
            'BRAND_NAME': ['Brand A', 'Brand B']
        })

        with pytest.raises(ValueError, match="must contain 'standard_brand' column"):
            analysis_helpers.summarize_by_brand(df)

    def test_create_contingency_table(self):
        """Test contingency table creation."""
        df = pd.DataFrame({
            'brand': ['A', 'A', 'B', 'B', 'C', 'C'],
            'category': ['Cat1', 'Cat2', 'Cat1', 'Cat1', 'Cat2', 'Cat2']
        })

        table = analysis_helpers.create_contingency_table(df, 'brand', 'category')

        assert table.loc['A', 'Cat1'] == 1
        assert table.loc['A', 'Cat2'] == 1
        assert table.loc['B', 'Cat1'] == 2

    def test_create_contingency_table_normalized(self):
        """Test contingency table with normalization."""
        df = pd.DataFrame({
            'brand': ['A', 'A', 'B', 'B', 'B', 'B'],
            'category': ['Cat1', 'Cat2', 'Cat1', 'Cat1', 'Cat1', 'Cat2']
        })

        result = analysis_helpers.create_contingency_table(df, 'brand', 'category', normalize=True)

        assert 'counts' in result
        assert 'percentages' in result
        # Brand A: 50% Cat1, 50% Cat2
        assert abs(result['percentages'].loc['A', 'Cat1'] - 50.0) < 0.1
        assert abs(result['percentages'].loc['A', 'Cat2'] - 50.0) < 0.1
        # Brand B: 75% Cat1, 25% Cat2
        assert abs(result['percentages'].loc['B', 'Cat1'] - 75.0) < 0.1
        assert abs(result['percentages'].loc['B', 'Cat2'] - 25.0) < 0.1

    def test_chi_square_test(self):
        """Test chi-square test."""
        # Create data with clear association
        df = pd.DataFrame({
            'brand': ['A']*10 + ['B']*10,
            'problem': ['Problem1']*9 + ['Problem2']*1 + ['Problem2']*9 + ['Problem1']*1
        })

        result = analysis_helpers.chi_square_test(df, 'brand', 'problem')

        assert 'chi2_statistic' in result
        assert 'p_value' in result
        assert 'dof' in result
        assert 'expected_frequencies' in result
        assert 'significant' in result
        assert result['significant'] == True  # Should be significant

    def test_event_type_comparison(self):
        """Test event type comparison."""
        df = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5, 6],
            'standard_brand': ['Brand A', 'Brand A', 'Brand A', 'Brand B', 'Brand B', 'Brand B'],
            'EVENT_TYPE': ['Death', 'Injury', 'Malfunction', 'Death', 'Death', 'Injury']
        })

        comparison = analysis_helpers.event_type_comparison(df)

        assert 'counts' in comparison
        assert 'percentages' in comparison
        assert 'chi2_test' in comparison
        assert 'summary' in comparison
        assert isinstance(comparison['summary'], str)
        assert 'Brand A' in comparison['summary']
        assert 'Brand B' in comparison['summary']


@pytest.mark.integration
class TestAnalysisHelpersIntegration:
    """Integration tests with real test database."""

    @pytest.fixture
    def db_with_data(self, tmp_path):
        """Create test database with sample data."""
        db_path = str(tmp_path / 'test.db')
        db = MaudeDatabase(db_path, verbose=False)

        # Create sample device data
        device_data = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5],
            'BRAND_NAME': ['Test Device A', 'Test Device B', 'Test Device A', 'Test Device C', 'Test Device B'],
            'GENERIC_NAME': ['Device Type 1', 'Device Type 2', 'Device Type 1', 'Device Type 3', 'Device Type 2'],
            'MANUFACTURER_D_NAME': ['Acme Corp', 'Beta Inc', 'Acme Corp', 'Gamma LLC', 'Beta Inc'],
            'DATE_RECEIVED': ['2020-01-15', '2020-06-20', '2021-03-10', '2021-08-05', '2021-12-25'],
            'EVENT_TYPE': ['Death', 'Injury', 'Malfunction', 'Death', 'Injury']
        })

        # Insert into database
        device_data.to_sql('device', db.conn, if_exists='replace', index=False)

        # Create master table entry
        master_data = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2, 3, 4, 5],
            'DATE_RECEIVED': ['2020-01-15', '2020-06-20', '2021-03-10', '2021-08-05', '2021-12-25'],
            'EVENT_TYPE': ['Death', 'Injury', 'Malfunction', 'Death', 'Injury']
        })
        master_data.to_sql('master', db.conn, if_exists='replace', index=False)

        yield db
        db.close()

    def test_query_multiple_devices_workflow(self, db_with_data):
        """Test full multi-device query workflow."""
        brands = ['Test Device A', 'Test Device B']
        results = analysis_helpers.query_multiple_devices(
            db_with_data, brands
        )

        assert len(results) > 0
        assert 'query_brand' in results.columns
        assert 'all_matching_brands' in results.columns
        # Should find devices with either brand
        assert results['query_brand'].isin(brands).all()

    def test_query_multiple_devices_deduplication(self, db_with_data):
        """Test that query_multiple_devices deduplicates correctly."""
        brands = ['Test Device']  # Partial match will find multiple
        results = analysis_helpers.query_multiple_devices(
            db_with_data, brands, deduplicate=True
        )

        # Should have no duplicate MDR_REPORT_KEYs
        assert len(results) == results['MDR_REPORT_KEY'].nunique()

    def test_enrich_missing_table_raises_error(self, db_with_data):
        """Test strict error when table not loaded."""
        df = pd.DataFrame({'MDR_REPORT_KEY': [1, 2, 3]})

        with pytest.raises(ValueError, match="Problems table not loaded"):
            analysis_helpers.enrich_with_problems(db_with_data, df)

        with pytest.raises(ValueError, match="Patient table not loaded"):
            analysis_helpers.enrich_with_patient_data(db_with_data, df)

        with pytest.raises(ValueError, match="Text table not loaded"):
            analysis_helpers.enrich_with_narratives(db_with_data, df)

    def test_find_brand_variations(self, db_with_data):
        """Test finding brand variations."""
        variations = analysis_helpers.find_brand_variations(db_with_data, 'Test Device')

        assert len(variations) > 0
        assert 'BRAND_NAME' in variations.columns
        assert 'count' in variations.columns
        assert 'sample_mdr_keys' in variations.columns

    def test_find_brand_variations_multiple_terms(self, db_with_data):
        """Test finding variations with multiple search terms."""
        variations = analysis_helpers.find_brand_variations(
            db_with_data, ['Device A', 'Device B']
        )

        assert len(variations) > 0

    def test_get_narratives_for_wrapper(self, db_with_data):
        """Test get_narratives_for with database instance."""
        # Create text table
        text_data = pd.DataFrame({
            'MDR_REPORT_KEY': [1, 2],
            'FOI_TEXT': ['Event narrative 1', 'Event narrative 2']
        })
        text_data.to_sql('text', db_with_data.conn, if_exists='replace', index=False)

        results = pd.DataFrame({'MDR_REPORT_KEY': [1, 2, 3]})
        narratives = analysis_helpers.get_narratives_for(db_with_data, results)

        assert len(narratives) == 2  # Only 2 have narratives
        assert 'FOI_TEXT' in narratives.columns

    def test_backwards_compatibility_via_db_instance(self, db_with_data):
        """Test that existing methods still work through database instance."""
        results = db_with_data.query_device(device_name='Test Device A')

        # Test old helper methods
        trends = db_with_data.trends_for(results)
        assert len(trends) > 0

        breakdown = db_with_data.event_type_breakdown_for(results)
        assert 'total' in breakdown

        top_mfg = db_with_data.top_manufacturers_for(results)
        assert len(top_mfg) > 0

        date_summary = db_with_data.date_range_summary_for(results)
        assert 'first_date' in date_summary

    def test_new_methods_via_db_instance(self, db_with_data):
        """Test that new methods work through database instance."""
        # Test query_multiple_devices
        results = db_with_data.query_multiple_devices(['Test Device A', 'Test Device B'])
        assert len(results) > 0

        # Test standardize_brand_names
        mapping = {'test device a': 'Device A', 'test device b': 'Device B'}
        standardized = db_with_data.standardize_brand_names(results, mapping)
        assert 'standard_brand' in standardized.columns

        # Test summarize_by_brand
        summary = db_with_data.summarize_by_brand(standardized)
        assert 'counts' in summary

        # Test find_brand_variations
        variations = db_with_data.find_brand_variations('Test Device')
        assert len(variations) > 0

    def test_query_device_catalog_basic(self, db_with_data):
        """Test basic query_device_catalog functionality."""
        catalog = [
            {
                'device_id': 'DEVICE_A',
                'search_terms': ['Test Device A'],
                'pma_pmn_numbers': []
            },
            {
                'device_id': 'DEVICE_B',
                'search_terms': ['Test Device B'],
                'pma_pmn_numbers': []
            }
        ]

        results = analysis_helpers.query_device_catalog(db_with_data, catalog)

        assert len(results) > 0
        assert 'device_id' in results.columns
        assert 'matched_via' in results.columns
        assert set(results['device_id'].unique()) <= {'DEVICE_A', 'DEVICE_B'}

    def test_query_device_catalog_multiple_search_terms(self, db_with_data):
        """Test catalog with multiple search terms per device."""
        catalog = [
            {
                'device_id': 'DEVICE_GROUP',
                'search_terms': ['Test Device A', 'Test Device B', 'Test Device C'],
                'pma_pmn_numbers': []
            }
        ]

        results = analysis_helpers.query_device_catalog(db_with_data, catalog)

        assert len(results) > 0
        assert 'device_id' in results.columns
        assert (results['device_id'] == 'DEVICE_GROUP').all()
        # Should have matched via different search terms
        assert 'matched_via' in results.columns

    def test_query_device_catalog_with_pmn(self, db_with_data):
        """Test catalog search using PMN/PMA numbers."""
        # Add PMA_PMN_NUM to master table
        db_with_data.conn.execute("ALTER TABLE master ADD COLUMN PMA_PMN_NUM TEXT")
        db_with_data.conn.execute("UPDATE master SET PMA_PMN_NUM = 'P123456' WHERE MDR_REPORT_KEY = 1")
        db_with_data.conn.commit()

        catalog = [
            {
                'device_id': 'DEVICE_WITH_PMN',
                'search_terms': [],
                'pma_pmn_numbers': ['P123456']
            }
        ]

        results = analysis_helpers.query_device_catalog(db_with_data, catalog)

        assert len(results) >= 1
        assert 'device_id' in results.columns
        assert (results['device_id'] == 'DEVICE_WITH_PMN').all()
        # Should have one result matched via PMN
        pmn_matches = results[results['matched_via'].str.contains('PMN:')]
        assert len(pmn_matches) >= 1

    def test_query_device_catalog_deduplication(self, db_with_data):
        """Test that catalog deduplicates within device."""
        catalog = [
            {
                'device_id': 'DEVICE_A',
                'search_terms': ['Test Device', 'Device A'],  # Both will match same reports
                'pma_pmn_numbers': []
            }
        ]

        results = analysis_helpers.query_device_catalog(db_with_data, catalog)

        # Should have no duplicate MDR_REPORT_KEYs within the same device
        device_a_results = results[results['device_id'] == 'DEVICE_A']
        assert len(device_a_results) == device_a_results['MDR_REPORT_KEY'].nunique()

    def test_query_device_catalog_with_date_filters(self, db_with_data):
        """Test catalog with date filtering."""
        catalog = [
            {
                'device_id': 'DEVICE_2021',
                'search_terms': ['Test Device'],
                'pma_pmn_numbers': []
            }
        ]

        results = analysis_helpers.query_device_catalog(
            db_with_data, catalog,
            start_date='2021-01-01',
            end_date='2021-12-31'
        )

        # Should only get 2021 results
        if len(results) > 0:
            assert all(pd.to_datetime(results['DATE_RECEIVED']).dt.year == 2021)

    def test_query_device_catalog_empty_results(self, db_with_data):
        """Test catalog with no matching devices."""
        catalog = [
            {
                'device_id': 'NONEXISTENT',
                'search_terms': ['Device That Does Not Exist'],
                'pma_pmn_numbers': []
            }
        ]

        results = analysis_helpers.query_device_catalog(db_with_data, catalog)

        assert len(results) == 0
        assert isinstance(results, pd.DataFrame)

    def test_query_device_catalog_missing_device_id(self, db_with_data):
        """Test that missing device_id raises error."""
        catalog = [
            {
                'search_terms': ['Test Device'],
                'pma_pmn_numbers': []
            }
        ]

        with pytest.raises(ValueError, match="must have a 'device_id' field"):
            analysis_helpers.query_device_catalog(db_with_data, catalog)

    def test_query_device_catalog_via_db_instance(self, db_with_data):
        """Test that query_device_catalog works through database instance."""
        catalog = [
            {
                'device_id': 'DEVICE_A',
                'search_terms': ['Test Device A'],
                'pma_pmn_numbers': []
            }
        ]

        results = db_with_data.query_device_catalog(catalog)
        assert len(results) > 0
        assert 'device_id' in results.columns

    def test_hierarchical_brand_standardization_via_db_instance(self, db_with_data):
        """Test hierarchical standardization through database instance."""
        results = db_with_data.query_device(device_name='Test Device')

        specific = {
            'test device a': 'Test Device A (Specific)',
        }
        family = {
            'test device': 'Test Device (Generic)',
        }
        manufacturer = {
            'test device': 'Test Manufacturer',
        }

        result = db_with_data.hierarchical_brand_standardization(
            results,
            specific_mapping=specific,
            family_mapping=family,
            manufacturer_mapping=manufacturer
        )

        assert 'device_model' in result.columns
        assert 'device_family' in result.columns
        assert 'manufacturer' in result.columns
        assert len(result) == len(results)  # Should preserve all rows

    def test_hierarchical_brand_standardization_integration_workflow(self, db_with_data):
        """Test full workflow: query -> hierarchical standardization -> analysis."""
        # Query devices
        results = db_with_data.query_multiple_devices(['Test Device A', 'Test Device B'])

        # Apply hierarchical standardization
        specific = {
            'test device a': 'Device A Specific Model',
            'test device b': 'Device B Specific Model',
        }
        # Manufacturer mapping needs to match MANUFACTURER_D_NAME column values
        manufacturer = {
            'acme': 'Test Corp',
            'beta': 'Test Corp',
        }

        standardized = db_with_data.hierarchical_brand_standardization(
            results,
            specific_mapping=specific,
            manufacturer_mapping=manufacturer
        )

        # Analyze by manufacturer
        mfr_summary = db_with_data.summarize_by_brand(
            standardized,
            group_column='manufacturer'
        )

        assert 'counts' in mfr_summary
        assert 'Test Corp' in mfr_summary['counts']
        assert mfr_summary['counts']['Test Corp'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
