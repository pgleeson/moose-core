# -*- coding: utf-8 -*-
# reader.py ---
# 
# Filename: reader.py
# Description:
# Author: Subhasis Ray, Padraig Gleeson
# Maintainer: 
# Created: Wed Jul 24 15:55:54 2013 (+0530)
# Version: 
# Last-Updated: 15 Jan 2018
#           By: pgleeson
#     Update #: --
# URL:
# Keywords:
# Compatibility:
#
#

# Commentary:
#
#
#
#

# Change log:
#
#
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street, Fifth
# Floor, Boston, MA 02110-1301, USA.
#
#

# Code:
"""Implementation of reader for NeuroML 2 models.


TODO: handle morphologies of more than one segment...

"""

from __future__ import print_function
try:
    from future_builtins import zip, map
except ImportError:
    pass
import sys, os
import numpy as np
from moose.neuroml2.hhfit import exponential2
from moose.neuroml2.hhfit import sigmoid2
from moose.neuroml2.hhfit import linoid2
from moose.neuroml2.units import SI
import moose
import logging
import math

loglevel = logging.DEBUG
logstream = logging.StreamHandler()
logstream.setLevel(loglevel)
logstream.setFormatter(logging.Formatter('%s(asctime)s %(name)s %(filename)s %(funcName)s: %(message)s'))
logger = logging.getLogger('nml2_reader')
logger.addHandler(logstream)

try:
    import neuroml as nml
    import neuroml.loaders as loaders
    from pyneuroml import pynml
except:
    print("********************************************************************")
    print("* ")
    print("*  Please install libNeuroML & pyNeuroML: ")
    print("*    pip install libneuroml")
    print("*    pip install pyNeuroML")
    print("* ")
    print("*  Requirement for this is lxml: ")
    print("*    apt-get install python-lxml")
    print("* ")
    print("********************************************************************")

# Utility functions

def sarea(comp):
    """
    Return the surface area of compartment from length and
    diameter.

    Parameters
    ----------
    comp : Compartment instance.

    Returns
    -------
    s : float
        surface area of `comp`.

    """
    if comp.length > 0:
        return comp.length * comp.diameter * np.pi
    else:
        return comp.diameter * comp.diameter * np.pi

def xarea(comp):
    """
    Return the cross sectional area from diameter of the
    compartment. How to do it for spherical compartment?"""
    return comp.diameter * comp.diameter * np.pi / 4.0

def setRa(comp, resistivity):
    """Calculate total raxial from specific value `resistivity`"""
    if comp.length > 0:
        comp.Ra = resistivity * comp.length / xarea(comp)
    else:
        comp.Ra = resistivity * 8.0 / (comp.diameter * np.pi)

def setRm(comp, condDensity):
    """Set membrane resistance"""
    comp.Rm = 1/(condDensity * sarea(comp))

def setEk(comp, erev):
    """Set reversal potential"""
    comp.setEm(erev)


def getSegments(nmlcell, component, sg_to_segments):
    """Get the list of segments the `component` is applied to"""
    sg = component.segment_groups
    #seg = component.segment
    if sg is None:
            segments = nmlcell.morphology.segments
    elif sg == 'all': # Special case
        segments = [seg for seglist in sg_to_segments.values() for seg in seglist]
    else:
        segments = sg_to_segments[sg]
        
    unique_segs = []
    unique_segs_ids = []
    for s in segments:
        if not s.id in unique_segs_ids:
            unique_segs.append(s)
            unique_segs_ids.append(s.id)
    return unique_segs


class NML2Reader(object):
    """Reads NeuroML2 and creates MOOSE model. 

    NML2Reader.read(filename) reads an NML2 model under `/library`
    with the toplevel name defined in the NML2 file.

    Example:

    >>> from moose import neuroml2 as nml
    >>> reader = nml.NML2Reader()
    >>> reader.read('moose/neuroml2/test_files/Purk2M9s.nml')

    creates a passive neuronal morphology `/library/Purk2M9s`.
    """
    def __init__(self, verbose=False):
        self.lunit = 1e-6 # micron is the default length unit
        self.verbose = verbose
        self.doc = None
        self.filename = None        
        self.nml_cells_to_moose = {} # NeuroML object to MOOSE object
        self.nml_segs_to_moose = {} # NeuroML object to MOOSE object
        self.nml_chans_to_moose = {} # NeuroML object to MOOSE object
        self.nml_conc_to_moose = {} # NeuroML object to MOOSE object
        self.moose_to_nml = {} # Moose object to NeuroML object
        self.proto_cells = {} # map id to prototype cell in moose
        self.proto_chans = {} # map id to prototype channels in moose
        self.proto_pools = {} # map id to prototype pools (Ca2+, Mg2+)
        self.includes = {} # Included files mapped to other readers
        self.lib = moose.Neutral('/library')
        self.id_to_ionChannel = {}
        self._cell_to_sg = {} # nml cell to dict - the dict maps segment groups to segments
        
        self.cells_in_populations = {}
        self.pop_to_cell_type = {}
        self.seg_id_to_comp_name = {}
        self.paths_to_chan_elements = {}

    def read(self, filename, symmetric=True):
        self.doc = loaders.read_neuroml2_file(filename, include_includes=True, verbose=self.verbose)
        
        if self.verbose:
            print('Parsed NeuroML2 file: %s'% filename)
        self.filename = filename
        
        if len(self.doc.networks)>=1:
            self.network = self.doc.networks[0]
            
            moose.celsius = self._getTemperature()
            
        self.importConcentrationModels(self.doc)
        self.importIonChannels(self.doc)
        self.importInputs(self.doc)
        
        
        for cell in self.doc.cells:
            self.createCellPrototype(cell, symmetric=symmetric)
            
        if len(self.doc.networks)>=1:
            self.createPopulations()
            self.createInputs()
        print("Read all from %s"%filename)
        
    def _getTemperature(self):
        if self.network.type=="networkWithTemperature":
            return SI(self.network.temperature)
        else:
            return 0 # Why not, if there's no temp dependence in nml..?
        
    def getCellInPopulation(self, pop_id, index):
        return self.cells_in_populations[pop_id][index]
    
    def getComp(self, pop_id, cellIndex, segId):
        return moose.element('%s/%s/%s/%s' % (self.lib.path, pop_id, cellIndex, self.seg_id_to_comp_name[self.pop_to_cell_type[pop_id]][segId]))
            
    def createPopulations(self):
        for pop in self.network.populations:
            mpop = moose.Neutral('%s/%s' % (self.lib.path, pop.id))
            self.cells_in_populations[pop.id] ={}
            for i in range(pop.size):
                print("Creating %s/%s instances of %s under %s"%(i,pop.size,pop.component, mpop))
                self.pop_to_cell_type[pop.id]=pop.component
                chid = moose.copy(self.proto_cells[pop.component], mpop, '%s'%(i))
                self.cells_in_populations[pop.id][i]=chid
                
                
    def getInput(self, input_id):
        return moose.element('%s/inputs/%s'%(self.lib.path,input_id))
               
                
    def createInputs(self):
        for el in self.network.explicit_inputs:
            pop_id = el.target.split('[')[0]
            i = el.target.split('[')[1].split(']')[0]
            seg_id = 0
            if '/' in el.target:
                seg_id = el.target.split('/')[1]
            input = self.getInput(el.input)
            moose.connect(input, 'output', self.getComp(pop_id,i,seg_id), 'injectMsg')
            
        for il in self.network.input_lists:
            for ii in il.input:
                input = self.getInput(il.component)
                moose.connect(input, 'output', self.getComp(il.populations,ii.get_target_cell_id(),ii.get_segment_id()), 'injectMsg')
            

    def createCellPrototype(self, cell, symmetric=True):
        """To be completed - create the morphology, channels in prototype"""
        nrn = moose.Neuron('%s/%s' % (self.lib.path, cell.id))
        self.proto_cells[cell.id] = nrn
        self.nml_cells_to_moose[cell.id] = nrn
        self.moose_to_nml[nrn] = cell
        self.createMorphology(cell, nrn, symmetric=symmetric)
        self.importBiophysics(cell, nrn)
        return cell, nrn


    def createMorphology(self, nmlcell, moosecell, symmetric=True):
        """Create the MOOSE compartmental morphology in `moosecell` using the
        segments in NeuroML2 cell `nmlcell`. Create symmetric
        compartments if `symmetric` is True.

        """
        morphology = nmlcell.morphology
        segments = morphology.segments
        id_to_segment = dict([(seg.id, seg) for seg in segments])    
        if symmetric:
            compclass = moose.SymCompartment
        else:
            compclass = moose.Compartment
        # segment names are used as compartment names - assuming
        # naming convention does not clash with that in MOOSE
        cellpath = moosecell.path
        id_to_comp = {}
        self.seg_id_to_comp_name[nmlcell.id]={}
        for seg in segments:
            if seg.name is not None:
                id_to_comp[seg.id] = compclass('%s/%s' % (cellpath, seg.name))
                self.seg_id_to_comp_name[nmlcell.id][seg.id] = seg.name
            else:
                name = 'comp_%s'%seg.id
                id_to_comp[seg.id] = compclass('%s/%s' % (cellpath, name))
                self.seg_id_to_comp_name[nmlcell.id][seg.id] = name
        # Now assign the positions and connect up axial resistance
        if not symmetric:
            src, dst = 'axial', 'raxial'
        else:
            src, dst = 'proximal', 'distal'
        for segid, comp in id_to_comp.items():
            segment = id_to_segment[segid]
            try:
                parent = id_to_segment[segment.parent.segments]
            except AttributeError:
                parent = None
            self.moose_to_nml[comp] = segment
            self.nml_segs_to_moose[segment.id] = comp            
            p0 = segment.proximal            
            if p0 is None:
                if parent:
                    p0 = parent.distal
                else:
                    raise Exception('No proximal point and no parent segment for segment: name=%s, id=%s' % (segment.name, segment.id))
            comp.x0, comp.y0, comp.z0 = (x * self.lunit for x in map(float, (p0.x, p0.y, p0.z)))
            p1 = segment.distal
            comp.x, comp.y, comp.z = (x * self.lunit for x in map(float, (p1.x, p1.y, p1.z)))
            comp.length = np.sqrt((comp.x - comp.x0)**2
                                  + (comp.y - comp.y0)**2
                                  + (comp.z - comp.z0)**2)
            # This can pose problem with moose where both ends of
            # compartment have same diameter. We are averaging the two
            # - may be splitting the compartment into two is better?
            comp.diameter = (float(p0.diameter)+float(p1.diameter)) * self.lunit / 2
            if parent:
                pcomp = id_to_comp[parent.id]
                moose.connect(comp, src, pcomp, dst)
        sg_to_segments = {}        
        for sg in morphology.segment_groups:
            sg_to_segments[sg.id] = [id_to_segment[m.segments] for m in sg.members]
        for sg in morphology.segment_groups:
            if not sg.id in sg_to_segments:
                sg_to_segments[sg.id] = []
            for inc in sg.includes:
                for cseg in sg_to_segments[inc.segment_groups]:
                    sg_to_segments[sg.id].append(cseg)
            
        if not 'all' in sg_to_segments:
            sg_to_segments['all'] = [ s for s in segments ]
            
        self._cell_to_sg[nmlcell.id] = sg_to_segments
        return id_to_comp, id_to_segment, sg_to_segments

    def importBiophysics(self, nmlcell, moosecell):
        """Create the biophysical components in moose Neuron `moosecell`
        according to NeuroML2 cell `nmlcell`."""
        bp = nmlcell.biophysical_properties
        if bp is None:
            print('Warning: %s in %s has no biophysical properties' % (nmlcell.id, self.filename))
            return
        self.importMembraneProperties(nmlcell, moosecell, bp.membrane_properties)
        self.importIntracellularProperties(nmlcell, moosecell, bp.intracellular_properties)

    def importMembraneProperties(self, nmlcell, moosecell, mp):
        """Create the membrane properties from nmlcell in moosecell"""
        if self.verbose:
            print('Importing membrane properties')
        self.importCapacitances(nmlcell, moosecell, mp.specific_capacitances)
        self.importChannelsToCell(nmlcell, moosecell, mp)
        self.importInitMembPotential(nmlcell, moosecell, mp)

    def importCapacitances(self, nmlcell, moosecell, specificCapacitances):
        sg_to_segments = self._cell_to_sg[nmlcell.id]
        for specific_cm in specificCapacitances:
            cm = SI(specific_cm.value)
            for seg in sg_to_segments[specific_cm.segment_groups]:
                comp = self.nml_segs_to_moose[seg.id]
                comp.Cm = sarea(comp) * cm
                
    def importInitMembPotential(self, nmlcell, moosecell, membraneProperties):
        sg_to_segments = self._cell_to_sg[nmlcell.id]
        for imp in membraneProperties.init_memb_potentials:
            initv = SI(imp.value)
            for seg in sg_to_segments[imp.segment_groups]:
                comp = self.nml_segs_to_moose[seg.id]
                comp.initVm = initv 

    def importIntracellularProperties(self, nmlcell, moosecell, properties):
        self.importAxialResistance(nmlcell, properties)
        self.importSpecies(nmlcell, properties)

    def importSpecies(self, nmlcell, properties):
        sg_to_segments = self._cell_to_sg[nmlcell.id]
        for species in properties.species:
            if (species.concentration_model is not None) and \
               (species.concentration_model.id  not in self.proto_pools):
                continue
            segments = getSegments(nmlcell, species, sg_to_segments)
            for seg in segments:
                comp = self.nml_segs_to_moose[seg.id]    
                self.copySpecies(species, comp)

    def copySpecies(self, species, compartment):
        """Copy the prototype pool `species` to compartment. Currently only
        decaying pool of Ca2+ supported"""
        proto_pool = None
        if species.concentrationModel in self.proto_pools:
            proto_pool = self.proto_pools[species.concentration_model]
        else:
            for innerReader in self.includes.values():
                if species.concentrationModel in innerReader.proto_pools:
                    proto_pool = innerReader.proto_pools[species.concentrationModel]
                    break
        if not proto_pool:
            raise Exception('No prototype pool for %s referred to by %s' % (species.concentration_model, species.id))
        pool_id = moose.copy(proto_pool, comp, species.id)
        pool = moose.element(pool_id)
        pool.B = pool.B / (np.pi * compartment.length * (0.5 * compartment.diameter + pool.thickness) * (0.5 * compartment.diameter - pool.thickness))        
        return pool

    def importAxialResistance(self, nmlcell, intracellularProperties):
        sg_to_segments = self._cell_to_sg[nmlcell.id]
        for r in intracellularProperties.resistivities:
            segments = getSegments(nmlcell, r, sg_to_segments)
            for seg in segments:
                comp = self.nml_segs_to_moose[seg.id]
                setRa(comp, SI(r.value))     
                
    def isPassiveChan(self,chan):
        if chan.type == 'ionChannelPassive':
            return True
        if hasattr(chan,'gates'):
            return len(chan.gate_hh_rates)+len(chan.gates)==0
        return False
    

    rate_fn_map = {
        'HHExpRate': exponential2,
        'HHSigmoidRate': sigmoid2,
        'HHSigmoidVariable': sigmoid2,
        'HHExpLinearRate': linoid2 }

    def calculateRateFn(self, ratefn, vmin, vmax, tablen=3000, vShift='0mV'):
        """Returns A / B table from ngate."""
        tab = np.linspace(vmin, vmax, tablen)
        if self._is_standard_nml_rate(ratefn):
            midpoint, rate, scale = map(SI, (ratefn.midpoint, ratefn.rate, ratefn.scale))
            return self.rate_fn_map[ratefn.type](tab, rate, scale, midpoint)
        else:
            for ct in self.doc.ComponentType:
                if ratefn.type == ct.name:
                    print("Using %s to evaluate rate"%ct.name)
                    rate = []
                    for v in tab:
                        vals = pynml.evaluate_component(ct,req_variables={'v':'%sV'%v,'vShift':vShift,'temperature':self._getTemperature()})
                        '''print vals'''
                        if 'x' in vals:
                            rate.append(vals['x'])
                        if 't' in vals:
                            rate.append(vals['t'])
                        if 'r' in vals:
                            rate.append(vals['r'])
                    return np.array(rate)

    def importChannelsToCell(self, nmlcell, moosecell, membrane_properties):
        sg_to_segments = self._cell_to_sg[nmlcell.id]
        for chdens in membrane_properties.channel_densities + membrane_properties.channel_density_v_shifts:
            segments = getSegments(nmlcell, chdens, sg_to_segments)
            condDensity = SI(chdens.cond_density)
            erev = SI(chdens.erev)
            try:
                ionChannel = self.id_to_ionChannel[chdens.ion_channel]
            except KeyError:
                print('No channel with id', chdens.ion_channel)                
                continue
                
            if self.verbose:
                print('Setting density of channel %s in %s to %s; erev=%s (passive: %s)'%(chdens.id, segments, condDensity,erev,self.isPassiveChan(ionChannel)))
            
            if self.isPassiveChan(ionChannel):
                for seg in segments:
                    comp = self.nml_segs_to_moose[seg.id]
                    setRm(comp, condDensity)
                    setEk(comp, erev)
            else:
                for seg in segments:
                    self.copyChannel(chdens, self.nml_segs_to_moose[seg.id], condDensity, erev)
            '''moose.le(self.nml_segs_to_moose[seg.id])
            moose.showfield(self.nml_segs_to_moose[seg.id], field="*", showtype=True)'''

    def copyChannel(self, chdens, comp, condDensity, erev):
        """Copy moose prototype for `chdens` condutcance density to `comp`
        compartment.

        """
        proto_chan = None
        if chdens.ion_channel in self.proto_chans:
            proto_chan = self.proto_chans[chdens.ion_channel]
        else:
            for innerReader in self.includes.values():
                if chdens.ionChannel in innerReader.proto_chans:
                    proto_chan = innerReader.proto_chans[chdens.ion_channel]
                    break
        if not proto_chan:
            raise Exception('No prototype channel for %s referred to by %s' % (chdens.ion_channel, chdens.id))

        if self.verbose:
            print('Copying %s to %s, %s; erev=%s'%(chdens.id, comp, condDensity, erev))
        orig = chdens.id
        chid = moose.copy(proto_chan, comp, chdens.id)
        chan = moose.element(chid)
        els = list(self.paths_to_chan_elements.keys())
        for p in els:
            pp = p.replace('%s/'%chdens.ion_channel,'%s/'%orig)
            self.paths_to_chan_elements[pp] = self.paths_to_chan_elements[p].replace('%s/'%chdens.ion_channel,'%s/'%orig)
        #print(self.paths_to_chan_elements)
        chan.Gbar = sarea(comp) * condDensity
        chan.Ek = erev
        moose.connect(chan, 'channel', comp, 'channel')
        return chan    

    '''
    def importIncludes(self, doc):        
        for include in doc.include:
            if self.verbose:
                print(self.filename, 'Loading include', include)
            error = None
            inner = NML2Reader(self.verbose)
            paths = [include.href, os.path.join(os.path.dirname(self.filename), include.href)]
            for path in paths:
                try:
                    inner.read(path)                    
                    if self.verbose:
                        print(self.filename, 'Loaded', path, '... OK')
                except IOError as e:
                    error = e
                else:
                    self.includes[include.href] = inner
                    self.id_to_ionChannel.update(inner.id_to_ionChannel)
                    self.nml_to_moose.update(inner.nml_to_moose)
                    self.moose_to_nml.update(inner.moose_to_nml)
                    error = None
                    break
            if error:
                print(self.filename, 'Last exception:', error)
                raise IOError('Could not read any of the locations: %s' % (paths))'''
                
    def _is_standard_nml_rate(self, rate):
        return rate.type=='HHExpLinearRate' \
               or rate.type=='HHExpRate' or \
               rate.type=='HHSigmoidRate' or \
               rate.type=='HHSigmoidVariable'

    def createHHChannel(self, chan, vmin=-150e-3, vmax=100e-3, vdivs=5000):
        mchan = moose.HHChannel('%s/%s' % (self.lib.path, chan.id))
        mgates = map(moose.element, (mchan.gateX, mchan.gateY, mchan.gateZ))
        assert(len(chan.gate_hh_rates) <= 3) # We handle only up to 3 gates in HHCHannel
        
        if self.verbose:
            print('== Creating channel: %s (%s) -> %s (%s)'%(chan.id, chan.gate_hh_rates, mchan, mgates))
        all_gates = chan.gates + chan.gate_hh_rates
        for ngate, mgate in zip(all_gates,mgates):
            if mgate.name.endswith('X'):
                mchan.Xpower = ngate.instances
            elif mgate.name.endswith('Y'):
                mchan.Ypower = ngate.instances
            elif mgate.name.endswith('Z'):
                mchan.Zpower = ngate.instance
            mgate.min = vmin
            mgate.max = vmax
            mgate.divs = vdivs

            # I saw only examples of GateHHRates in
            # HH-channels, the meaning of forwardRate and
            # reverseRate and steadyState are not clear in the
            # classes GateHHRatesInf, GateHHRatesTau and in
            # FateHHTauInf the meaning of timeCourse and
            # steady state is not obvious. Is the last one
            # refering to tau_inf and m_inf??
            fwd = ngate.forward_rate
            rev = ngate.reverse_rate
            
            self.paths_to_chan_elements['%s/%s'%(chan.id,ngate.id)] = '%s/%s'%(chan.id,mgate.name)
                
            q10_scale = 1
            if ngate.q10_settings:
                if ngate.q10_settings.type == 'q10Fixed':
                    q10_scale= float(ngate.q10_settings.fixed_q10)
                elif ngate.q10_settings.type == 'q10ExpTemp':
                    q10_scale = math.pow(float(ngate.q10_settings.q10_factor),(self._getTemperature()- SI(ngate.q10_settings.experimental_temp))/10)
                    #print('Q10: %s; %s; %s; %s'%(ngate.q10_settings.q10_factor, self._getTemperature(),SI(ngate.q10_settings.experimental_temp),q10_scale))
                else:
                    raise Exception('Unknown Q10 scaling type %s: %s'%(ngate.q10_settings.type,ngate.q10_settings))
                    
            if self.verbose:
                print(' === Gate: %s; %s; %s; %s; %s; scale=%s'%(ngate.id, mgate.path, mchan.Xpower, fwd, rev, q10_scale))
                
            if (fwd is not None) and (rev is not None):
                alpha = self.calculateRateFn(fwd, vmin, vmax, vdivs)
                beta = self.calculateRateFn(rev, vmin, vmax, vdivs)
                mgate.tableA = q10_scale * (alpha)
                mgate.tableB = q10_scale * (alpha + beta)
            # Assuming the meaning of the elements in GateHHTauInf ...
            if hasattr(ngate,'time_course') and hasattr(ngate,'steady_state') \
               and (ngate.time_course is not None) and (ngate.steady_state is not None):
                tau = ngate.time_course
                inf = ngate.steady_state
                tau = self.calculateRateFn(tau, vmin, vmax, vdivs)
                inf = self.calculateRateFn(inf, vmin, vmax, vdivs)
                mgate.tableA = q10_scale * (inf / tau)
                mgate.tableB = q10_scale * (1 / tau)
                
            if hasattr(ngate,'steady_state') and (ngate.time_course is None) and (ngate.steady_state is not None):
                inf = ngate.steady_state
                tau = 1 / (alpha + beta)
                if (inf is not None):
                    inf = self.calculateRateFn(inf, vmin, vmax, vdivs)
                    mgate.tableA = q10_scale * (inf / tau)
                    mgate.tableB = q10_scale * (1 / tau)
                
        if self.verbose:
            print(self.filename, '== Created', mchan.path, 'for', chan.id)
        return mchan

    def createPassiveChannel(self, chan):
        mchan = moose.Leakage('%s/%s' % (self.lib.path, chan.id))
        if self.verbose:
            print(self.filename, 'Created', mchan.path, 'for', chan.id)
        return mchan

    def importInputs(self, doc):
        minputs = moose.Neutral('%s/inputs' % (self.lib.path))
        for pg_nml in doc.pulse_generators:

            pg = moose.PulseGen('%s/%s' % (minputs.path, pg_nml.id))
            pg.firstDelay = SI(pg_nml.delay)
            pg.firstWidth = SI(pg_nml.duration)
            pg.firstLevel = SI(pg_nml.amplitude)
            pg.secondDelay = 1e9
        

    def importIonChannels(self, doc, vmin=-150e-3, vmax=100e-3, vdivs=5000):
        if self.verbose:
            print(self.filename, 'Importing the ion channels')
            
        for chan in doc.ion_channel+doc.ion_channel_hhs:
            if chan.type == 'ionChannelHH':
                mchan = self.createHHChannel(chan)
            elif self.isPassiveChan(chan):
                mchan = self.createPassiveChannel(chan)
            else:
                mchan = self.createHHChannel(chan)
                
            self.id_to_ionChannel[chan.id] = chan
            self.nml_chans_to_moose[chan.id] = mchan
            self.proto_chans[chan.id] = mchan
            if self.verbose:
                print(self.filename, 'Created ion channel', mchan.path, 'for', chan.type, chan.id)

    def importConcentrationModels(self, doc):
        for concModel in doc.decaying_pool_concentration_models:
            proto = self.createDecayingPoolConcentrationModel(concModel)

    def createDecayingPoolConcentrationModel(self, concModel):
        """Create prototype for concentration model"""        
        if concModel.name is not None:
            name = concModel.name
        else:
            name = concModel.id
        ca = moose.CaConc('%s/%s' % (self.lib.path, id))
        print('11111', concModel.restingConc)
        print('2222', concModel.decayConstant)
        print('33333', concModel.shellThickness)

        ca.CaBasal = SI(concModel.restingConc)
        ca.tau = SI(concModel.decayConstant)
        ca.thick = SI(concModel.shellThickness)
        ca.B = 5.2e-6 # B = 5.2e-6/(Ad) where A is the area of the shell and d is thickness - must divide by shell volume when copying
        self.proto_pools[concModel.id] = ca
        self.nml_concs_to_moose[concModel.id] = ca
        self.moose_to_nml[ca] = concModel
        logger.debug('Created moose element: %s for nml conc %s' % (ca.path, concModel.id))




# 
# reader.py ends here
