######################################
#####     Curve finding           ####
######################################

def find_curve(P, DB, NE, prec, sign_ap = 1, magma = None, return_all = False, initial_data = None, ramification_at_infinity = None, **kwargs):
    r'''
    EXAMPLES:

    First we load the file::

    sage: %runfile findcurve.sage

    First example::

    sage: find_curve(5,6,30,20)

    A second example, now over a real quadratic::

    sage: F.<r> = QuadraticField(5)
    sage: P = F.ideal(3/2*r + 1/2)
    sage: D = F.ideal(3)
    sage: find_curve(P,D,P*D,30,ramification_at_infinity = F.real_places()[:1])

    Now over a cubic of mixed signature::

    sage: F.<r> = NumberField(x^3 -3)
    sage: P = F.ideal(r-2)
    sage: D = F.ideal(r-1)
    sage: find_curve(P,D,P*D,30)

    '''
    from sage.rings.padics.precision_error import PrecisionError
    from util import discover_equation,fwrite,quaternion_algebra_invariants_from_ramification, direct_sum_of_maps, config_section_map, Bunch
    from sarithgroup import BigArithGroup
    from homology import construct_homology_cycle,lattice_homology_cycle
    from cohomology import CohomologyGroup, get_overconvergent_class_quaternionic
    from integrals import integrate_H1,double_integral_zero_infty
    import os, datetime, ConfigParser

    config = ConfigParser.ConfigParser()
    config.read('config.ini')
    param_dict = config_section_map(config, 'General')
    param_dict.update(config_section_map(config, 'FindCurve'))
    param_dict.update(kwargs)
    param = Bunch(**param_dict)

    # Get general parameters
    outfile = param.outfile
    use_ps_dists = param.use_ps_dists
    use_sage_db = param.use_sage_db
    magma_seed = param.magma_seed
    parallelize = param.parallelize
    Up_method = param.up_method
    use_magma = param.use_magma
    progress_bar = param.progress_bar
    sign_at_infinity = param.sign_at_infinity

    # Get find_curve specific parameters
    grouptype = param.grouptype
    hecke_bound = param.hecke_bound
    timeout = param.timeout
    check_conductor = param.check_conductor

    if initial_data is None:
        try:
            page_path = ROOT + '/KleinianGroups-1.0/klngpspec'
        except NameError:
            ROOT = os.getcwd()
            page_path = ROOT + '/KleinianGroups-1.0/klngpspec'
        if magma is None:
            from sage.interfaces.magma import Magma
            quit_when_done = True
            magma = Magma()
        else:
            quit_when_done = False
        if magma_seed is not None:
            magma.eval('SetSeed(%s)'%magma_seed)
        magma.attach_spec(page_path)
        magma.eval('Page_initialized := true')
    else:
        quit_when_done = False

    sys.setrecursionlimit(10**6)

    global qE, Linv, G, Coh, phiE, xgen, xi1, xi2, Phi

    try:
        F = P.ring()
        Fdisc = F.discriminant()
        if not (P*DB).divides(NE):
            raise ValueError,'Conductor (NE) should be divisible by P*DB'
        p = ZZ(P.norm()).abs()

    except AttributeError:
        F = QQ
        P = ZZ(P)
        p = ZZ(P)
        Fdisc = ZZ(1)
        if NE % (P*DB) != 0:
            raise ValueError,'Conductor (NE) should be divisible by P*DB'

    Np = NE / (P * DB)
    if use_ps_dists is None:
        use_ps_dists = False # More efficient our own implementation

    if not p.is_prime():
        raise ValueError,'P (= %s) should be a prime, of inertia degree 1'%P

    working_prec = max([2 * prec + 10, 100])

    sgninfty = 'plus' if sign_at_infinity == 1 else 'minus'
    fname = 'moments_%s_%s_%s_%s_%s_%s.sobj'%(Fdisc,p,DB,NE,sgninfty,prec)

    if outfile is None:
        outfile = '%s_%s_%s_%s_%s.log'%(P,NE,sgninfty,prec,datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        outfile = outfile.replace('/','div')
        outfile = '/tmp/findcurve_' + outfile

    if F != QQ and ramification_at_infinity is None:
        if F.signature()[0] > 1:
            if F.signature()[1] == 1:
                ramification_at_infinity = F.real_places(prec = Infinity) # Totally 'definite'
            else:
                raise ValueError,'Please specify the ramification at infinity'
        elif F.signature()[0] == 1:
            if len(F.ideal(DB).factor()) % 2 == 0:
                ramification_at_infinity = [] # Split at infinity
            else:
                ramification_at_infinity = F.real_places(prec = Infinity) # Ramified at infinity
        else:
            ramification_at_infinity = None

    if outfile is not None:
        print "Partial results will be saved in %s"%outfile
    print '=' * 60

    if initial_data is not None:
        G,phiE = initial_data
    else:
        # Define the S-arithmetic group
        try:
            if F == QQ:
                abtuple = QuaternionAlgebra(DB).invariants()
            else:
                abtuple = quaternion_algebra_invariants_from_ramification(F,DB,ramification_at_infinity)
            G = BigArithGroup(P, abtuple, Np, use_sage_db = use_sage_db, grouptype = grouptype, magma = magma, seed = magma_seed, timeout = timeout)
        except RuntimeError as e:
            if quit_when_done:
                magma.quit()
            mystr = str(e.message)
            if len(mystr) > 30:
                mystr = mystr[:14] + ' ... ' + mystr[-14:]
            if return_all:
                return ['Error when computing G: ' + mystr]
            else:
                return 'Error when computing G: ' + mystr

        # Define phiE, the cohomology class associated to the system of eigenvalues.
        Coh = CohomologyGroup(G.Gpn)
        phiE = Coh.get_rational_cocycle(sign = sign_at_infinity,bound = hecke_bound,return_all = return_all,use_magma = True)
        # except Exception as e:
        #     if quit_when_done:
        #         magma.quit()
        #     if return_all:
        #         return ['Error when finding cohomology class: ' + str(e.message)]
        #     else:
        #         return 'Error when finding cohomology class: ' + str(e.message)
        if use_sage_db:
            G.save_to_db()
        print 'Cohomology class found'
    try:
        wp = G.wp()
        B = G.Gpn.abelianization()
        C = G.Gn.abelianization()
        Bab = B.abelian_group()
        Cab = C.abelian_group()
        verbose('Finding f...')
        fdata = [B.ab_to_G(o).quaternion_rep for o in B.gens_small()]
        # verbose('fdata = %s'%fdata)
        f = B.hom_from_image_of_gens_small([C.G_to_ab(G.Gn(o)) for o in fdata])
        verbose('Finding g...')
        gdata = [wp**-1 * o * wp for o in fdata]
        # verbose('gdata = %s'%gdata)
        g = B.hom_from_image_of_gens_small([C.G_to_ab(G.Gn(o)) for o in gdata])
        fg = direct_sum_of_maps([f,g])
        V = Bab.gen(0).lift().parent()
        good_ker = V.span_of_basis([o.lift() for o in fg.kernel().gens()]).LLL().rows()
        ker = [B.ab_to_G(Bab(o)) for o in good_ker]
    except Exception as e:
        if quit_when_done:
            magma.quit()
        if return_all:
            return ['Problem calculating homology kernel: ' + str(e.message)]
        else:
            return 'Problem calculating homology kernel: ' + str(e.message)

    if not return_all:
        phiE = [phiE]
    ret_vals = []
    for phi in phiE:
        try:
            Phi = get_overconvergent_class_quaternionic(P,phi,G,prec,sign_at_infinity,sign_ap,use_ps_dists,method = Up_method, progress_bar = progress_bar)
        except ValueError as e:
            ret_vals.append('Problem when getting overconvergent class: ' + str(e.message))
            continue
        print 'Done overconvergent lift'
        # Find an element x of Gpn for not in the kernel of phi,
        # and such that both x and wp^-1 * x * wp are trivial in the abelianization of Gn.
        try:
            found = False
            for o in ker:
                if phi.evaluate(o) != 0:
                    found = True
                    break
            if not found:
                raise RuntimeError('Cocycle evaluates always to zero')
        except Exception as e:
            ret_vals.append('Problem when choosing element in kernel: ' + str(e.message))
            continue
        xgen = o
        found = False
        while not found:
            try:
                xi1, xi2 = lattice_homology_cycle(G,xgen,working_prec,outfile = outfile)
                found = True
            except PrecisionError:
                working_prec  = 2 * working_prec
                verbose('Setting working_prec to %s'%working_prec)
            # except Exception as e:
            #     ret_vals.append('Problem when computing homology cycle: ' + str(e.message))
            #     break
        try:
            qE1 = integrate_H1(G,xi1,Phi,1,method = 'moments',prec = working_prec, twist = False,progress_bar = progress_bar)
            qE2 = integrate_H1(G,xi2,Phi,1,method = 'moments',prec = working_prec, twist = True,progress_bar = progress_bar)
        except Exception as e:
            ret_vals.append('Problem with integration: %s'%str(e.message))
            continue

        qE = qE1/qE2
        qE = qE.add_bigoh(prec + qE.valuation())
        Linv = qE.log(p_branch = 0)/qE.valuation()

        print 'Integral done. Now trying to recognize the curve'
        fwrite('F.<r> = NumberField(%s)'%(F.gen(0).minpoly()),outfile)
        fwrite('N_E = %s = %s'%(NE,factor(NE)),outfile)
        fwrite('D_B = %s = %s'%(DB,factor(DB)),outfile)
        fwrite('Np = %s = %s'%(Np,factor(Np)),outfile)
        fwrite('Calculation with p = %s and prec = %s+%s'%(P,prec,working_prec-prec),outfile)
        fwrite('qE = %s'%qE,outfile)
        fwrite('Linv = %s'%Linv,outfile)
        curve = discover_equation(qE,G._F_to_local,NE,prec,check_conductor = check_conductor)
        if curve is None:
            if quit_when_done:
                magma.quit()
            ret_vals.append('None')
        else:
            try:
                curve = curve.global_minimal_model()
            except AttributeError,NotImplementedError:
                pass
            fwrite('EllipticCurve(F, %s )'%(list(curve.a_invariants())), outfile)
            fwrite('=' * 60, outfile)
            ret_vals.append(str(curve.a_invariants()))
    if quit_when_done:
        magma.quit()
    if return_all:
        return ret_vals
    else:
        return ret_vals[0]
