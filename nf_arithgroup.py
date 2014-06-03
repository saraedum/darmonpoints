######################
##                  ##
##    QUATERNIONIC  ##
##    ARITHMETIC    ##
##    GROUP         ##
##                  ##
######################
from sage.structure.sage_object import SageObject
from sage.misc.all import cached_method,lazy_attribute,walltime
from sage.groups.group import AlgebraicGroup
from sage.structure.element import MultiplicativeGroupElement
from sage.structure.parent import Parent
from sage.algebras.quatalg.all import QuaternionAlgebra
from sage.matrix.all import matrix,Matrix
from sage.modules.all import vector
from sage.rings.all import RealField,ComplexField,RR,QuadraticField,PolynomialRing,NumberField,lcm
from sage.rings.padics.all import Qp
from sage.functions.trig import arctan
from sage.interfaces.magma import magma
from sage.all import prod
from collections import defaultdict
from itertools import product,chain,izip,groupby,islice,tee,starmap
from sigma0 import Sigma0,Sigma0ActionAdjuster
from util import *
from homology import Divisors, Homology
from sage.structure.sage_object import save,load
from copy import copy
from sage.misc.persist import db
from sage.modules.free_module import FreeModule_generic
from rational_arithgroup import ArithGroupElement,ArithGroup_generic

class ArithGroup_nf_quaternion(ArithGroup_generic):
    Element = ArithGroupElement
    def __init__(self,base,a,b,level,info_magma = None):
        self.F = base
        #self.discriminant = base(discriminant)
        self.level = base.ideal(level)
        self.a,self.b = base(a),base(b)
        self.__init_magma_objects(info_magma)

        self.B = QuaternionAlgebra(self.F,self.a,self.b)

        magma_ZBasis = self._O_magma.ZBasis()
        tmpObasis = [magma_quaternion_to_sage(self.B,o) for o in magma_ZBasis]
        self.Obasis = tmpObasis
        Obasis = [[u for o in elt.coefficient_tuple() for u in o.list()] for elt in tmpObasis]
        self.basis_invmat = matrix(QQ,4*self.F.degree(),4*self.F.degree(),Obasis).transpose().inverse()

        self._O_discriminant = magma_F_ideal_to_sage(self.F,self._O_magma.Discriminant())
        verbose('Computing normalized basis')
        _,f,e = self._O_magma.NormalizedBasis(nvals = 3)
        verbose('Computing presentation')
        G,gens = f.Presentation(e,self._O_magma,nvals = 2)
        verbose('Done with presentation')
        self._facerels_magma = f
        self._G_magma = G
        self._H_magma,self._GtoH_magma = magma.ReduceGenerators(G,nvals = 2)
        self.Ugens = []
        for h in self._H_magma.gens():
            newgen = self.B(1)
            for i,ai in shorten_word(G(h).ElementToSequence()._sage_()):
                newgen = newgen * magma_quaternion_to_sage(self.B,gens[i+1])**ai
            self.Ugens.append(newgen)
        self.F_units = self.F.unit_group()
        self.F_unit_offset = len(self.Ugens)
        for u in self.F_units.gens():
            self.Ugens.append(self.B(self.F(u)))

        verbose('Initializing generators')
        self._gens = [ ArithGroupElement(self,quaternion_rep = g, word_rep = [(i,1)],check = False) for i,g in enumerate(self.Ugens) ]

        verbose('Initializing relations')
        temp_relation_words = [shorten_word(self._H_magma.Relations()[n+1].LHS().ElementToSequence()._sage_()) for n in range(len(self._H_magma.Relations()))] + [[(self.F_unit_offset + i,u.multiplicative_order())] for i,u in enumerate(self.F_units.gens()) if u.multiplicative_order() != Infinity]

        self._relation_words = []
        for rel in temp_relation_words:
            remaining_unit = self.F_units(self.F(prod((self._gens[g].quaternion_rep**a for g,a in rel), z = self.B(1))))
            assert remaining_unit.multiplicative_order() != Infinity
            ulist = remaining_unit.exponents()
            newrel = rel + [(self.F_unit_offset + i,a) for i,a in enumerate(ulist) if a != 0 ]
            sign = ZZ(prod((self._gens[g].quaternion_rep**a for g,a in newrel), z = self.B(1)))
            assert sign == 1
            self._relation_words.append(newrel)

        verbose('Initializing abmatrix')
        # Define the (abelian) relation matrix
        self._relation_matrix = matrix(ZZ,len(self._relation_words),len(self._gens),0)
        for i,rel in enumerate(self._relation_words):
            for j,k in rel:
                self._relation_matrix[i,j] += k
        Parent.__init__(self)

    def _repr_(self):
        return 'Arithmetic Group attached to quaternion algebra with a = %s, b = %s and level = %s'%(self.a,self.b,self.level)

    def __init_magma_objects(self,info_magma = None):
        wtime = walltime()
        verbose('Calling _init_magma_objects...')
        if info_magma is None:
            Qx_magma = magma.PolynomialRing(magma.Rationals())
            xm = Qx_magma.gen(1)
            f = self.F.gen().minpoly()
            FF_magma = magma.NumberField(sum([magma(c)*xm**i for c,i in zip(f.coefficients(),f.exponents())]))
            self._F_magma = FF_magma
            OF_magma = FF_magma.Integers()
            am, bm = sage_F_elt_to_magma(self._F_magma,self.a),sage_F_elt_to_magma(self._F_magma,self.b)
            self._B_magma = magma.QuaternionAlgebra(FF_magma,am,bm)

            self._Omax_magma = self._B_magma.MaximalOrder()
            self._O_magma = self._Omax_magma.Order(sage_F_ideal_to_magma(self._F_magma,self.level))
        else:
            self._F_magma = info_magma._F_magma
            OF_magma = info_magma._F_magma.Integers()
            self._B_magma = info_magma._B_magma
            self._Omax_magma = info_magma._B_magma.MaximalOrder()
            self._O_magma = self._Omax_magma.Order(sage_F_ideal_to_magma(self._F_magma,self.level))
        verbose('Spent %s seconds in init_magma_objects'%walltime(wtime))

    def _quaternion_to_list(self,x):
        xlist = [u for o in x.coefficient_tuple() for u in o.list()]
        tmp = (self.basis_invmat * matrix(QQ,4 * self.F.degree() ,1,xlist)).list()
        return tmp

    @cached_method
    def get_word_rep(self,delta):
        if not self._is_in_order(delta):
            raise RuntimeError,'delta (= %s) is not in order!'%delta
        c = self.__magma_word_problem(delta)
        tmp = [(g-1,len(list(a))) if g > 0 else (-g-1,-len(list(a))) for g,a in groupby(c)]
        delta1 =  prod((self.Ugens[g]**a for g,a in tmp))
        quo = delta/delta1
        assert quo.is_constant()
        quo = quo.coefficient_tuple()[0]
        exps = self.F_units(quo).exponents()
        tmp.extend([(self.F_unit_offset + i,a) for i,a in enumerate(exps) if a != 0])
        delta1 =  prod((self.Ugens[g]**a for g,a in tmp))
        quo = ZZ(delta1/delta)
        assert quo == 1
        return tmp

    def __magma_word_problem(self,x):
        r'''
        Given a quaternion x, finds its decomposition in terms of the generators

        INPUT: x can be a list/vector of integers (giving the quaternion in terms of the basis for the order,
        or x can be a quaternion, in which case the conversion is done in the function.

        OUTPUT: A list representing a word in the generators

        EXAMPLES:

        sage: G = ArithGroup(7,15,1)
        sage: G.__magma_word_problem(G.Ugens[2]*G.Ugens[1]) == [2,1]
        '''
        wtime = walltime()
        # If x is a quaternion, find the expression in the generators.
        xm = sage_quaternion_to_magma(self._B_magma,self.B(x))
        V = self._GtoH_magma.Image(magma.Word(xm,self._facerels_magma,self._G_magma)).ElementToSequence()._sage_()
        verbose('Just spent %s seconds in Magma (x = %s)'%(walltime(wtime),x))
        return V


    def _is_in_order(self,x):
        return all([o.is_integral() for o in self._quaternion_to_list(x)])

    def enumerate_elements(self,max_length = None):
        ngens = self.F_unit_offset #len(self.gens())
        for v in enumerate_words(range(ngens)):
            if max_length is not None and len(v) > max_length:
                raise StopIteration
            else:
                yield prod([self.Ugens[i] for i in v])

    def compute_quadratic_embedding(self,K,return_generator = False):
        O_magma = self._O_magma
        F_magma = self._F_magma

        assert K.base_field() == self.F
        Fxmagma = magma.PolynomialRing(F_magma)
        Fxmagma.assign_names('x')
        xm = Fxmagma.gen(1)
        b = K.gen()
        f = b.minpoly()
        fm = sum([sage_F_elt_to_magma(self._F_magma,c) * xm**i for c,i in zip(f.coefficients(),f.exponents())])
        K_magma = magma.NumberField(fm)
        OK_magma = K_magma.MaximalOrder()
        verbose('Calling magma Embed function...')
        try:
            _,iota = magma.Embed(OK_magma,O_magma,nvals = 2)
        except RuntimeError:
            print 'An error ocurred!'
            print 'OK_magma = ',OK_magma
            print 'O_magma =',O_magma
            raise RuntimeError
        verbose('Calling magma Embed function done!')
        wm = K_magma(OK_magma.Basis()[2])
        w = K(magma_F_elt_to_sage(self.F,wm[1]) + magma_F_elt_to_sage(self.F,wm[2]) * b)
        ans = magma_integral_quaternion_to_sage(self.B,O_magma,F_magma,iota.Image(OK_magma(K_magma.gen(1))))
        # ans = magma_quaternion_to_sage(self.B,self._B_magma(iota.Image(OK_magma(K_magma.gen(1)))))
        assert ans.reduced_norm() == K.gen().norm(self.F) and ans.reduced_trace() == K.gen().trace(self.F)
        ans = self.B(ans)
        if return_generator:
            verbose('w = %s, minpoly = %s'%(w,w.minpoly()))
            assert w in K.maximal_order()
            return ans,w
        else:
            return ans

    def embed_order(self,p,K,prec,zero_deg = True,outfile = None,return_all = False):
        r'''
        '''
        verbose('Computing quadratic embedding to precision %s'%prec)
        mu = self.compute_quadratic_embedding(K,return_generator = False)
        verbose('Finding module generators')
        w = module_generators(K)[1]
        verbose('Done')
        w_minpoly = PolynomialRing(Qp(p,prec),names = 'x')([self._F_to_Qp(o) for o in w.minpoly().coeffs()])
        verbose('w_minpoly = %s'%w_minpoly)
        Cp = Qp(p,prec).extension(w_minpoly,names = 'g')
        verbose('Cp is %s'%Cp)
        wl = w.list()
        assert len(wl) == 2
        r0 = -wl[0]/wl[1]
        r1 = 1/wl[1]
        assert r0+r1*w == K.gen()
        padic_Kgen = Cp(self._F_to_Qp(r0))+Cp(self._F_to_Qp(r1))*Cp.gen()
        try:
            fwrite('d_K = %s, h_K = %s, h_K^- = %s'%(K.discriminant(),K.class_number(),len(K.narrow_class_group())),outfile)
        except NotImplementedError: pass
        fwrite('w_K satisfies: %s'%w.minpoly(),outfile)
        assert K.gen(0).trace(K.base_ring()) == mu.reduced_trace() and K.gen(0).norm(K.base_ring()) == mu.reduced_norm()

        iotap = self.get_embedding(prec)
        fwrite('Local embedding B to M_2(Q_p) sends i to %s and j to %s'%(iotap(self.B.gens()[0]).change_ring(Qp(p,5)).list(),iotap(self.B.gens()[1]).change_ring(Qp(p,5)).list()),outfile)
        a,b,c,d = iotap(mu).list()
        X = PolynomialRing(Cp,names = 'X').gen()
        tau1 = (Cp(a-d) + 2*padic_Kgen)/Cp(2*c)
        tau2 = (Cp(a-d) - 2*padic_Kgen)/Cp(2*c)
        assert (Cp(c)*tau1**2 + Cp(d-a)*tau1-Cp(b)) == 0
        assert (Cp(c)*tau2**2 + Cp(d-a)*tau2-Cp(b)) == 0

        found = False
        u = find_the_unit_of(self.F,K)
        assert u.is_integral() and (1/u).is_integral()
        gammalst = u.list()
        assert len(gammalst) == 2
        gammaquatrep = self.B(gammalst[0]) + self.B(gammalst[1]) * mu
        verbose('gammaquatrep trd = %s and nrd = %s'%(gammaquatrep.reduced_trace(),gammaquatrep.reduced_norm()))
        assert gammaquatrep.reduced_trace() == u.trace(self.F) and gammaquatrep.reduced_norm() == u.norm(self.F)
        gammaq = gammaquatrep
        while True:
            try:
                gamma = self(gammaq)
                break
            except ValueError:
                gammaq *= gammaquatrep
        fwrite('\cO_K to R_0 given by w_K |-> %s'%mu,outfile)
        fwrite('gamma_psi = %s'%gamma,outfile)
        fwrite('tau_psi = %s'%tau1,outfile)
        fwrite('(where g satisfies: %s)'%w.minpoly(),outfile)
        if return_all:
            return gamma, tau1, tau2
        else:
            return gamma, tau1

    def element_of_norm(self,N,use_magma = False,return_all = False,radius = -1,max_elements = -1):
        N = self.F.ideal(N)
        if return_all == False:
            try:
                return self._element_of_norm[N.gens_two()]
            except (AttributeError,KeyError):
                pass
        else:
            if radius < 0 and max_elements < 0:
                raise ValueError,'Radius must be positive'

        if not hasattr(self,'_element_of_norm'):
            self._element_of_norm  = dict([])

        if use_magma:
            assert return_all == False
            elt_magma = self._O_magma.ElementOfNorm(sage_F_ideal_to_magma(self._F_magma,N))
            elt_magma_vector = elt_magma.Vector()
            candidate = self.B([magma_F_elt_to_sage(self.F,elt_magma_vector[m+1]) for m in range(4)])
            self._element_of_norm[N.gens_two()] = candidate
            return candidate
        else:
            v = self.Obasis
            verbose('Doing long enumeration...')
            M = 0
            if return_all:
                all_candidates = []
            while M != radius:
                M += 1
                verbose('M = %s,radius = %s'%(M,radius))
                for a0,an in product(range(M),product(range(-M+1,M),repeat = len(v)-1)):
                    candidate = self.B(sum(ai*vi for ai,vi in  zip([a0]+list(an),v)))
                    if self.F.ideal(candidate.reduced_norm()) == N:
                        if not return_all:
                            self._element_of_norm[N] = candidate
                            return candidate
                        else:
                            self._element_of_norm[N] = candidate
                            all_candidates.append(candidate)
                            if len(all_candidates) == max_elements:
                                verbose('Found %s elements of requested norm'%len(all_candidates))
                                return all_candidates
            if return_all:
                verbose('Found %s elements of requested norm'%len(all_candidates))
                return all_candidates
            else:
                raise RuntimeError,'Not found'

    @cached_method
    def get_hecke_reps(self,l):
        r'''
        TESTS:

        sage: magma.eval('SetSeed(2000000)')
        sage: G = ArithGroup(6,5)
        sage: reps = G.get_hecke_reps(11)
        '''
        l = self.F.ideal(l)
        g0 = self.element_of_norm(l)
        reps = [g0]
        I = self.enumerate_elements()
        n_iters = ZZ(0)
        num_reps = l.norm() if l.divides(self._O_discriminant) else l.norm() + 1
        while len(reps) < num_reps:
            n_iters += 1
            if n_iters % 50 == 0:
                verbose('%s, len = %s/%s'%(n_iters,len(reps),num_reps))
            new_candidate = I.next() * g0
            new_inv = new_candidate**-1
            if not any([self._is_in_order(new_inv * old) for old in reps]):
                reps.append(new_candidate)
        return reps

    @cached_method
    def image_in_abelianized(self, x):
        r''' Given an element x in Gamma, returns its image in the abelianized group'''
        Gab,V,free_idx = self.abelianization()
        wd = x.word_rep
        tmp = Gab(sum(ZZ(a)*Gab(V.gen(g)) for g,a in wd))
        return (QQ**len(free_idx))([tmp[i] for i in free_idx])

    @cached_method
    def abelianization(self):
        # print 'Warning!! Loading W.sobj from disk, could be anything!'
        # return load('abelianized.sobj')
        V = ZZ**len(self.gens())
        W = V.span([sum(a*v for a,v in zip(V.gens(),rel)) for rel in self.get_relation_matrix().rows()])
        Gab = V/W
        free_idx = []
        for i in range(len(Gab.invariants())):
            if Gab.invariants()[i] == 0:
                free_idx.append(i)
        return Gab,V,free_idx
