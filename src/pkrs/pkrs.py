#!/home/fls530/anaconda3/bin/python

"""
Just like the 're' module; you pre-complie a GRS based on a dict of alt alleles and weights

# Pattern are the weights
# Compile function is the actual algorithm
# Results are obtained by applying (ie 'matching') 

"""

import collections
import logging
import math
import pathlib
import re
import sys

import pklib.pkcsv as csv
import pksnp.pksnp as pksnp

assert sys.version_info >= (3, 8), f"{sys.argv[0]} requires Python 3.8.0 or newer. Your version appears to be: '{sys.version}'."
logger = logging.getLogger(__name__)



#################################################
#
# --%%  CLASS: RiskScore  %%--

class RiskScore:
	"""An algorithm template object for holding the definition of a weight-based risk score.
	   Input should be an iterable of SNPs and an iterable of Alleles (with BETA defined)"""
	def __init__(self, risks, N=None, snps=None):
		self.beta   = dict()
		self.risks = self.ReadRisk(risks)
		self.N = len(self.risks) if N is None else float(N)
		assert self.N > 0, f"The denominator given with '-n' ('{self.N}') for the arithmetric mean must be >0."
		logger.debug(f"RiskScore: Setting N={self.N}")
		for risk in self.risks:
			self.beta[risk]   = float(risk.get("BETA",0))
		if snps:
			self.validate(snps)

	def calc(self, gtdict):
		"""This function implements a simple risk score based on a weighted sum.
		   gtdict:	Subject dict with str(var_id):float(dosage)"""
		wsum = 0
		gtlist = list(gtdict.values())
		alleles = {allele:allele.dosage for gt in gtlist for allele in gt.getAlleles()}
		for allele,wgt in self.beta.items():
			wsum += wgt * alleles.get(allele, 0)
			if alleles.get(allele):
				logger.debug(f"Calc Aggregate: '{allele}' found; weight = {wgt}, dosage = {alleles.get(allele,0)}; wsum = {wsum}")
		return wsum / self.N

	@staticmethod
	def ReadRisk(riskiter):
		"""Input: An iterator giving something with a 'get' method; Return: List of Alleles"""
		risks = []
		logger.debug(f"ReadRisk: {type(riskiter)}")
		for risk in riskiter:
			logger.debug(f"ReadRisk: {risk}")
			chrom = risk.get("CHROM", re.split(":", risk.get("POSID",":"))[0])
			pos   = risk.get("POS", re.split(":|_", risk.get("POSID",":"))[1])
			beta  = risk.get("BETA", math.log(float(risk.get("ODDSRATIO", 1))))
			try: risks.append(pksnp.Allele(CHROM=str(chrom), POS=int(pos), allele=str(risk.get("ALLELE")), BETA=float(beta)))
			except AttributeError as ae: 
				print("\n" + str(ae), file=sys.stderr)
				sys.exit("Read Error: Each line of '" + str(riskiter.get("name","weights file")) + "' must contain at least weight value with a recognizable position and allele.\n")
			except ValueError as ve:
				print("\n" + str(ve), file=sys.stderr)
				sys.exit("Read Error: Looks like some weights data are not following the expected format.")
		return risks

	def validate(self, snps):
		"""Validates that SNPs in the score match with SNPs in the input data."""
		if isinstance(snps, dict):
			snps = snps.values()
		snps   = dict(zip([s.ID for s in snps], snps))   # Dict of SNP instances
		for risk in self.risks:
			if risk not in snps:
				logger.warning(f"RiskScore: Weighted allele '{risk}' not found in subject data. Did you provide the correct subject variants?")




#################################################
#
# --%%  CLASS: PGSCatalog  %%--

class PGSCatalog(RiskScore):
	"""Class to handle risk scores downloaded from the PGSCatalog."""
	def __init__(self, pgs, *args, risks=[], **kwargs):
		"""Like RiskScore; just need to format the pgs risks correctly (pgs should be the return of pyclick.CSVFile() or similar)."""
		logger.debug(f"PGSCatalog: {type(pgs)}")
		if not risks:
			for line in pgs:
				logger.debug(f"PGSCatalog: {line}")
				risk = {}
				risk['RSID']   = line.get('rsID')
				risk['CHROM']  = line.get('chr_name')
				risk['POS']    = line.get('chr_position')
				risk['ALLELE'] = line.get('effect_allele')
				risk['BETA']   = line.get('effect_weight')
				risks.append(risk)
		super().__init__(risks=risks, *args, **kwargs)

"""
PGS Format from: https://www.pgscatalog.org/downloads/#scoring_columns
rsID	dbSNP Accession ID (rsID)	Optional
chr_name	Location - Chromosome 	Required
chr_position	Location - Position within the Chromosome	Required
effect_allele	Effect Allele	Required
other_allele	Other allele(s)	Recommended
locus_name	Locus Name	Optional
is_haplotype
is_diplotype	FLAG: Haplotype or Diplotype	Optional
imputation_method	Imputation Method	Optional
variant_description	Variant Description	Optional
inclusion_criteria	Score Inclusion Criteria	Optional
effect_weight	Variant Weight	Required
is_interaction	FLAG: Interaction	Optional
is_dominant	FLAG: Dominant Inheritance Model	Optional
is_recessive	FLAG: Recessive Inheritance Model	Optional
dosage_0_weight	Effect weight with 0 copy of the effect allele	Optional
dosage_1_weight	Effect weight with 1 copy of the effect allele	Optional
dosage_2_weight
"""




#################################################
#
# --%%  CLASS: MultiRiskScore  %%--

class MultiRiskScore(RiskScore):
	"""Calculate GRS based on MultiLocus Weights."""
	def __init__(self, risks, multirisks, *args, **kwargs):
		super().__init__(risks=risks, *args, **kwargs)
		self.multi = self.ReadMultiRisk(multirisks)

	def calc(self, gtdict, **kwargs): # This guy still works on two levels; isn't nested like ReadMultiRisk now is.
		"""Calculate the Multilocus part of a GRS.
		   gtdict => dict {str(id):GenoType}; RETURN: A risk score (float)"""
		wsum = super().calc(gtdict, **kwargs)
		if mrs := self.nested_lookup(self.multi, gtdict.values()):
			logger.debug(f"Calc MultiRiskScore: found weight = {mrs}")
			wsum += mrs / self.N
		logger.debug(f"MultiRiskScore: Total score = {wsum}")
		return wsum

	@staticmethod
	def nested_lookup(nested_dict, subject): 
		if isinstance(nested_dict, dict):
			for haplo in nested_dict: # Pulling from nested ensures that the returned matching weight is the highest ranked (by fileorder); Also fast, only looping over existing keys.
				if haplo in subject:
					logger.debug(f"MultiRiskScore: Found allele '{haplo}' pointing to '{nested_dict[haplo]}'.")
					return MultiRiskScore.nested_lookup(nested_dict[haplo], [gt for gt in subject if gt != haplo]) # Move down in nested structure. Exclude haplo from subject so it isn't counted again.
		else:
			return nested_dict # Which should actually be the weight by now (a float)
		return 0


	@staticmethod
	def ReadMultiRisk(risk_iter):
		"""INPUT: A file object to read from; RETURN: An arbitrarily nested dict with the required genotypes/haplotypes as keys and the weights as the bottommost values.
		   We should probably write this with arbitrary nesting... It's not completely finished and is therefore intentionally dirty"""
		def nested_read(risk, nested_dict=dict(), i=1):
			chrom = risk.get("CHROM_" + str(i), risk.get("POSID_" + str(i),":").split(":")[0])
			pos   = risk.get("POS_" + str(i), risk.get("POSID_" + str(i),":").split(":")[1])
			myid  = risk.get("ID_" + str(i))
			try:
				gtype = pksnp.GenoType(ID=myid, CHROM=chrom, POS=pos, genotype=risk.get("GENOTYPE_" + str(i), "").split(":"))
			except (AssertionError, AttributeError) as ae:
				beta = float(risk.get("BETA", math.log(float(risk.get("ODDSRATIO", 1)))))
				assert beta and isinstance(nested_dict, dict), "Each line of multilocus weights file must contain one weight and at least one recognizable allele or genotype."
				return beta
			nested_dict[gtype] = nested_read(risk, nested_dict.get(gtype, dict()), i+1)
			return nested_dict

		nested_dict = dict()
		for risk in risk_iter:
			logging.debug(f"ReadMultiRisk: Reading {risk}")
			if risk.get("GENOTYPE_1"):
				nested_dict = nested_read(risk, nested_dict)
		return nested_dict




#################################################
#
# --%%  CLASS: Oram2016  %%--

class oram2016(MultiRiskScore):
	"""Calculate GRS based on Oram et al 2016"""
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.N = 2 * (self.N + 1)




#################################################
#
# --%%  CLASS: Shapr2019  %%--

class sharp2019(MultiRiskScore):
	"""Calculate GRS based on Sharp et al 2019"""
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.N = 1

	def calc(self, gtdict, **kwargs):
		"""From Sharp2019: For haplotypes with an interaction the beta is taken from Table S3, without an interaction it is scored independently for each haplotype of the pair."""
		wsum = super(MultiRiskScore,MultiRiskScore).calc(self, gtdict, **kwargs)
		if mrs := sum(self.nested_lookup(self.multi, gtdict.values())[:2]):
			logger.debug(f"Sharp2019: Found multirisk weights = {mrs}")
			wsum += mrs / self.N
		logger.debug(f"Sharp2019: Total score = {wsum}")
		return wsum

	@staticmethod
	def nested_lookup(nested_dict, subject):
		if wsum := super(sharp2019,sharp2019).nested_lookup(nested_dict, subject):
			return [wsum]
		wsum = []
		import itertools
		subject_alleles = list(itertools.chain(*[gt.getAlleles(True) for gt in subject]))
		if isinstance(nested_dict, dict):
			for haplo in nested_dict: # Pulling from nested ensures that the returned matching weight is the highest ranked (by fileorder); Also fast, only looping over existing keys.
				if haplo in subject_alleles:
					logger.debug(f"Sharp2019: Found allele '{haplo}' pointing to '{nested_dict[haplo]}'.")
					wsum.extend(sharp2019.nested_lookup(nested_dict[haplo], subject)) # Move down in nested structure.
		else:
			return [nested_dict] # Which should actually be the weight by now (a float)
		return wsum

	@staticmethod
	def ReadMultiRisk(risk_iter):
		"""Returns: A nested dict with Genotypes and Alleles as keys and the matching weights as leaf values.
		risk_iter => An iterable containing tab-separated data on genotypes/alleles and their risk weights."""
		import itertools
		(risk_iter1, risk_iter2) = itertools.tee(risk_iter,2)
		nested_dict = super(sharp2019, sharp2019).ReadMultiRisk(risk_iter1)

		def nested_read(risk, nested_dict=dict(), i=1):
			chrom = risk.get("CHROM_" + str(i), risk.get("POSID_" + str(i),":").split(":")[0])
			pos   = risk.get("POS_" + str(i), risk.get("POSID_" + str(i),":").split(":")[1])
			myid  = risk.get("ID_" + str(i))
			try:
				gtype = pksnp.Allele(ID=myid, CHROM=chrom, POS=pos, allele=risk.get("ALLELE_" + str(i), ""))
			except (AssertionError, AttributeError) as ae:
				beta = float(risk.get("BETA", math.log(float(risk.get("ODDSRATIO", 1)))))
				assert beta and isinstance(nested_dict, dict), "Each line of multilocus weights file must contain one weight and at least one recognizable allele or genotype."
				return beta
			nested_dict[gtype] = nested_read(risk, nested_dict.get(gtype, dict()), i+1)
			return nested_dict

		for risk in risk_iter2:
			if risk.get("ALLELE_1"):
				nested_dict = nested_read(risk, nested_dict)
		return nested_dict



