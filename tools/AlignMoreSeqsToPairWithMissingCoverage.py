#!/usr/bin/env python
from __future__ import print_function

## Author: Chris Wymant, c.wymant@imperial.ac.uk
## Acknowledgement: I wrote this while funded by ERC Advanced Grant PBDR-339251
##
## Overview:
ExplanatoryMessage = '''Aligns more sequences to a pairwise alignment in which
the first sequence contains missing coverage - the "?" character. Output is
printed to stdout suitable for redirection to a fasta-format file. The pairwise 
alignment is nominally the consensus (called from parsing mapped reads) and the
reference used for mapping, in that order. Alignment is performed using mafft;
mafft does not know what missing coverage is, hence the need for this program.
How it works: we replace missing coverage by gaps, realign, match the consensus
fragments after (which in general contain new gaps) with those before, then
replace the appropriate gaps by missing coverage.'''

import argparse
import os
import sys
import re
import copy
from Bio import SeqIO
from Bio import Seq
import itertools
import subprocess
import collections
from AuxiliaryFunctions import PropagateNoCoverageChar

# Define a function to check files exist, as a type for the argparse.
def File(MyFile):
  if not os.path.isfile(MyFile):
    raise argparse.ArgumentTypeError(MyFile+' does not exist or is not a file.')
  return MyFile

# Set up the arguments for this script
parser = argparse.ArgumentParser(description=ExplanatoryMessage)
parser.add_argument('OtherSeqsToBeAdded', type=File)
parser.add_argument('SeqPairWithMissingCov', type=File)
parser.add_argument('-F', '--addfragments', action='store_true', \
help='Call mafft with --addfragments instead of --add.')
parser.add_argument('-S', '--swap-seqs', action='store_true', \
help='Swap the consensus and the reference in the output (so that the order ' +\
'becomes consensus then reference then the other sequences added).')
parser.add_argument('-T1', '--temp-file-1', \
default='temp_AlnToMissingCovPair1.fasta')
parser.add_argument('-T2', '--temp-file-2', \
default='temp_AlnToMissingCovPair2.fasta')
parser.add_argument('--x-mafft', default='mafft', help=\
'The command required to invoke mafft (by default: mafft).')
args = parser.parse_args()

# Find the consensus and its ref
ConsensusFound = False
RefFound = False
for seq in SeqIO.parse(open(args.SeqPairWithMissingCov),'fasta'):
  if not ConsensusFound:
    consensus = seq
    ConsensusFound = True
    continue
  if not RefFound:
    ref = seq
    RefFound = True
    continue
  print('Found three sequences in', args.SeqPairWithMissingCov+\
  '; expected only two. Quitting.', file=sys.stderr)
  exit(1)
if not RefFound:
  print('Less than two sequences found in', args.SeqPairWithMissingCov+\
  '; expected two. Quitting.', file=sys.stderr)
  exit(1)

# Check the consensus and its ref are aligned with no pure-gap columns.
ConsensusAsString = str(consensus.seq)
RefAsString = str(ref.seq)
if len(ConsensusAsString) != len(RefAsString):
  print(args.SeqPairWithMissingCov, 'is not an alignment - seq lengths', \
  'differ. Quitting.', file=sys.stderr)
  exit(1)
for ConsensusBase, RefBase in itertools.izip(ConsensusAsString, RefAsString):
  if RefBase == '-':
    if ConsensusBase == '-':
      print("Found position in", args.SeqPairWithMissingCov, 'at which both', \
      'sequences have a gap. Such positions should be removed first.', \
      'Quitting.', file=sys.stderr)
      exit(1)
    if ConsensusBase == '?':
      print("Found position in", args.SeqPairWithMissingCov, 'at which the', \
      'consensus has a "?" character and the reference has a "-" character.', \
      'Such positions should be removed first. Quitting.', file=sys.stderr)
      exit(1)
    

# Replaces gaps that border "no coverage" by "no coverage".
ConsensusAsString = PropagateNoCoverageChar(ConsensusAsString)

# Check all seq IDs are unique.
AllIDs = [consensus.id, ref.id]
for seq in SeqIO.parse(open(args.OtherSeqsToBeAdded),'fasta'):
  AllIDs.append(seq.id)
if len(set(AllIDs)) < len(AllIDs):
  print('At least one sequence ID is duplicated in', \
  args.SeqPairWithMissingCov, 'and', args.OtherSeqsToBeAdded + \
  '. Sequence IDs should be unique. Quitting.', file=sys.stderr)
  exit(1)

# Align
ConsensusNoMissingCov = copy.copy(consensus)
ConsensusNoMissingCovStr = ConsensusAsString.replace('?', '-')
ConsensusNoMissingCov.seq = Seq.Seq(ConsensusNoMissingCovStr)
if args.swap_seqs:
  seqs = [ref, ConsensusNoMissingCov]
else:
  seqs = [ConsensusNoMissingCov, ref]
SeqIO.write(seqs, args.temp_file_1, "fasta")
if args.addfragments:
  AddOption = '--addfragments'
else:
  AddOption = '--add'
with open(args.temp_file_2, 'w') as f:
  try:
    ExitStatus = subprocess.call([args.x_mafft, '--quiet', '--preservecase', \
    AddOption, args.OtherSeqsToBeAdded, args.temp_file_1], stdout=f)
    assert ExitStatus == 0
  except:
    print('Problem calling mafft. Quitting.', file=sys.stderr)
    raise

# Read in the aligned seqs. Note which one is the consensus. Check all the 
# expected seqs are recovered.
AlignedSeqs = []
for i, seq in enumerate(SeqIO.parse(open(args.temp_file_2),'fasta')):
  AlignedSeqs.append(seq)
  if seq.id == consensus.id:
    ConsensusPosition = i
if sorted([seq.id for seq in AlignedSeqs]) != sorted(AllIDs):
  print('Error: different sequences found in', args.temp_file_2, \
  'compared to', args.SeqPairWithMissingCov, 'and', args.OtherSeqsToBeAdded + \
  '. Quitting.', file=sys.stderr)
  exit(1)

# Check the consensus only has changes in gaps.
PostAlignmentConsensus = AlignedSeqs[ConsensusPosition]
PostAlignmentConsensusAsStr = str(PostAlignmentConsensus.seq)
if PostAlignmentConsensusAsStr.replace('-','') != \
ConsensusNoMissingCovStr.replace('-',''):
  print('Error:', consensus.id, 'contains different bases before and after', \
  'alignment. Quitting.', file=sys.stderr)
  exit(1)

# To be used shortly
def CharToInt(char):
  if char == '?':
    return 0
  if char == '-':
    return 1
  return 2

# To be used shortly
def SplitSeqByGapsAndMissingCov(seq):
  '''Split up a sequence into runs of missing coverage, runs of gaps, and runs
  of bases.'''
  for i, base in enumerate(seq):
    BaseType = CharToInt(base)
    if i == 0:
      ListOfBitsOfSeq = [base]
      ListOfBitTypes = [BaseType]
      continue
    if BaseType == ListOfBitTypes[-1]:
      ListOfBitsOfSeq[-1] += base
    else:
      ListOfBitsOfSeq.append(base)
      ListOfBitTypes.append(BaseType)
  return ListOfBitsOfSeq, ListOfBitTypes

# Split up the consensus, pre- and post-alignment, into 'bits', namely runs of
# bases ('BitType' 2), runs of gaps ('BitType' 1) and runs of missing coverage
# ('BitType' 0).
PreAlnConsensusBits, PreAlnConsensusBitTypes = \
SplitSeqByGapsAndMissingCov(ConsensusAsString)
PostAlnConsensusBits, PostAlnConsensusBitTypes = \
SplitSeqByGapsAndMissingCov(PostAlignmentConsensusAsStr)

NewConsensus = ''
ProgThroughPostAln = 0
InsidePreAlnBaseRun = False
for ProgThroughPreAln, PreAlnConsensusBit in enumerate(PreAlnConsensusBits):
  PreAlnConsensusBitType  = PreAlnConsensusBitTypes[ProgThroughPreAln]
  PostAlnConsensusBit     = PostAlnConsensusBits[ProgThroughPostAln]
  PostAlnConsensusBitType = PostAlnConsensusBitTypes[ProgThroughPostAln]

  # A PreAln BitType 0 or 1 should become a 1 after alignment. We want the 
  # PostAln length of the bit (it could be longer due to accommodating a new 
  # insertion), but the PreAln BitType.
  if PreAlnConsensusBitType in [0,1]:
    if PostAlnConsensusBitType != 1:
      print('Error running', sys.argv[0] + ': gap or missing coverage became', \
      'something other than a gap after alignment. Please report to Chris', \
      'Wymant (google for current email address).', file=sys.stderr)
      exit(1)
    NewConsensus += PreAlnConsensusBit[0] * len(PostAlnConsensusBit)
    ProgThroughPostAln += 1
    continue

  # A PreAln BitType 2 can either stay the same, or be chopped into three bits
  # of type 2 1 2 (i.e. one run of gaps inserted), or be chopped into five bits 
  # of type 2 1 2 1 2 (two runs of gaps inserted) etc. We want to check this is 
  # the case, then just use the new form (chopped into gap-separated-bits
  # appropriately).
  if PostAlnConsensusBitType != 2:
    print('Error running', sys.argv[0] + ': sequence became', \
    'something other than sequence after alignment. Please report to Chris', \
    'Wymant (google for current email address).', file=sys.stderr)
    exit(1)
  PreAlnConsensusBitLength = len(PreAlnConsensusBit)
  if len(PostAlnConsensusBit) == PreAlnConsensusBitLength:
    NewConsensus += PreAlnConsensusBit
    ProgThroughPostAln += 1
    continue
  NewForm = ''
  while len(NewForm.replace('-', '')) < PreAlnConsensusBitLength:
    NewForm += PostAlnConsensusBits[ProgThroughPostAln]
    ProgThroughPostAln += 1
  if NewForm.replace('-', '') != PreAlnConsensusBit:
    print('Error running', sys.argv[0] + ': unable to match a split fragment', \
    'of consensus to the same fragment pre-alignment. Please report to Chris', \
    'Wymant (google for current email address).', file=sys.stderr)
    exit(1)
  NewConsensus += NewForm

# Output sanity checks
if NewConsensus.replace('?', '-') != PostAlignmentConsensusAsStr:
  print('Error running', sys.argv[0] + ': something went wrong replacing "-"', \
  'characters by of "?" characters. Please report to Chris', \
  'Wymant (google for current email address).', file=sys.stderr)
  exit(1)
if '?-' in NewConsensus or '-?' in NewConsensus:
  print('Error running', sys.argv[0] + ': found "-"', \
  'character next to "?" character in output. Please report to Chris', \
  'Wymant (google for current email address).', file=sys.stderr)
  exit(1)

AlignedSeqs[ConsensusPosition].seq = Seq.Seq(NewConsensus)

SeqIO.write(AlignedSeqs, sys.stdout, "fasta")
