from skimage.io import imread
from skimage.transform import radon, resize
import warnings
import numpy as np
import pywt
import scipy.interpolate as interpolate
from scipy.optimize import minimize
from scipy.signal import correlate
import time
import math
import sys
import scipy.sparse as sp
import os
import matplotlib.pyplot as plt
import argparse
import pathlib
from tqdm import tqdm
from cyt import tfun_cauchy as lcauchy, tfun_tikhonov as ltikhonov, tikhonov_grad, tfun_tv as ltv, tv_grad, cauchy_grad, \
    argumentspack

# Class to store results of one computation.
class container:
    def __init__(self,target=np.zeros((2,2)),l1=-1.0,l2=-1.0,result=np.zeros((2,2)),thinning=-1,noise=-1.0,imagefilename=None,targetsize=0,theta=np.zeros((1,)),method=None,prior=None,crimefree=False,totaliternum=0,levels=0,adaptnum=0,alpha=0.0,globalprefix=""):
        self.spent = time.time()
        self.l1 = l1
        self.l2 = l2
        self.target = target
        self.noise = noise
        self.crimefree = crimefree
        self.result = result
        self.imagefilename = imagefilename
        self.targetsize = targetsize
        self.theta = theta
        self.thinning = thinning
        self.method = method
        self.prior = prior
        self.totaliternum = totaliternum
        self.adaptnum = adaptnum
        self.alpha = alpha
        self.levels = levels
        self.globalprefix = globalprefix
        self.chain = None
        self.prefix = ''

    def finish(self,result=None,chain=None,error=(-1.0,-1.0),iters=None,thinning=-1):
        self.l1 = error[0]
        self.l2 = error[1]
        if iters is not None:
            self.totaliternum = iters
        if (chain is not None):
            self.thinning = thinning
            self.chain=chain
        self.result = result
        self.spent = time.time()-self.spent
        self.prefix =  time.strftime("%Y-%b-%d_%H_%M_%S") + '+' + self.prior + '+' + self.method + '+' + str(self.noise) + '+' + str(self.theta[0])+ '_' + str(self.theta[-1]) + '-'  + str(self.targetsize) + 'x' + str(len(self.theta))

class tomography:

    def __init__(self, filename, targetsize=128, itheta=50, noise=0.0,  commonprefix="", dimbig = 607, N_thetabig=421, crimefree=False,lhdev=None):
        self.globalprefix = str(pathlib.Path.cwd()) + commonprefix
        if not os.path.exists(self.globalprefix):
            os.makedirs(self.globalprefix)
        self.filename = filename
        self.dim = targetsize
        self.noise = noise
        self.thetabig = None
        self.dimbig = dimbig
        self.N_thetabig = N_thetabig
        self.N_rbig = math.ceil(np.sqrt(2) * self.dimbig)
        self.crimefree = crimefree
        if targetsize > 1100:
            raise Exception(
                'Dimensions of the target image are too large (' + str(targetsize) + 'x' + str(targetsize) + ')')

        img = imread(filename, as_gray=True)
        (dy, dx) = img.shape
        if (dy != dx):
            raise Exception('Image is not rectangular.')
        
        self.targetimage = imread(filename, as_gray=True)
        self.targetimage = resize(self.targetimage, (self.dim, self.dim), anti_aliasing=False, preserve_range=True,
                            order=1, mode='symmetric')
        if self.crimefree:
            image = imread(filename, as_gray=True)
            image = resize(image, (self.dimbig, self.dimbig), anti_aliasing=False, preserve_range=True,
                                order=1, mode='symmetric')
            (self.simsize, _) = image.shape

        else:
            image = imread(filename, as_gray=True)
            image = resize(image, (targetsize, targetsize), anti_aliasing=False, preserve_range=True, order=1,
                                mode='symmetric')
            (self.simsize, _) = image.shape

        self.flattened = np.reshape(image, (-1, 1))

        if isinstance(itheta, (int, np.int32, np.int64)) or (isinstance(itheta,(list,tuple)) and len(itheta) == 1):
            if  isinstance(itheta,(list,tuple)):
                itheta = itheta[0]
            self.theta = np.linspace(0., 180., itheta, endpoint=False)
            self.theta = self.theta / 360 * 2 * np.pi
            (self.N_r, self.N_theta) = (math.ceil(np.sqrt(2) * self.dim), itheta)
            self.rhoo = np.linspace(np.sqrt(2), -np.sqrt(2), self.N_r, endpoint=True)
            fname = 'radonmatrix/0_180-{0}x{1}.npz'.format(str(self.dim), str(self.N_theta))

            if self.crimefree:
                self.thetabig = np.linspace(0, 180, self.N_thetabig, endpoint=False)
                self.thetabig = self.thetabig / 360 * 2 * np.pi
                self.rhoobig = np.linspace(np.sqrt(2), -np.sqrt(2), self.N_rbig, endpoint=True)

        elif len(itheta) == 3:
            self.theta = np.linspace(itheta[0], itheta[1], itheta[2], endpoint=False)
            self.theta = self.theta / 360 * 2 * np.pi
            (self.N_r, self.N_theta) = (
                math.ceil(np.sqrt(2) * targetsize), itheta[2])
            self.rhoo = np.linspace(np.sqrt(2), -np.sqrt(2), self.N_r, endpoint=True)
            fname = 'radonmatrix/{0}_{1}-{2}x{3}.npz'.format(str(itheta[0]), str(itheta[1]), str(self.dim), str(self.N_theta))

            if (self.crimefree):
                self.thetabig = np.linspace(itheta[0], itheta[1], self.N_thetabig, endpoint=False)
                self.thetabig = self.thetabig / 360 * 2 * np.pi
                self.rhoobig = np.linspace(np.sqrt(2), -np.sqrt(2), self.N_rbig, endpoint=True)

        else:
            raise Exception('Invalid angle input.')

        if not os.path.isfile(fname):
            path = os.path.dirname(os.path.abspath(fname))
            if not os.path.exists(path):
                os.makedirs(path)

            from matrices import radonmatrix
            self.radonoperator = radonmatrix(self.dim, self.theta)
            sp.save_npz(fname, self.radonoperator)

        # In the case of inverse-crime free tomography,
        # one might use the Radon tool from scikit-image
        # or construct another Radon matrix and calculate a sinogram with that. The former is definitely faster and also preferred,
        # since different methods are used to simulate and reconcstruct the image.

        #if crimefree and (not os.path.isfile(fnamebig)):
        #    from matrices import radonmatrix

        #    self.radonoperatorbig = radonmatrix(self.dimbig, self.thetabig)
        #    sp.save_npz(fnamebig, self.radonoperatorbig)

        self.radonoperator = sp.load_npz(fname)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        self.radonoperator = self.radonoperator / self.dim

        if self.crimefree:
            #self.radonoperatorbig = sp.load_npz(fnamebig) / self.dimbig
            #simulated = self.radonoperatorbig@self.flattened
            #simulated = np.reshape(simulated,(self.N_rbig,self.N_thetabig))
            simulated = self.radonww(image,self.thetabig/ ( 2 * np.pi)*360)/self.dimbig
            simulated = np.reshape(simulated,(-1,1))

            maxvalue = np.max(simulated)
            simulated = simulated + maxvalue * self.noise * np.random.randn(self.N_rbig * self.N_thetabig, 1)
            self.sgramsim = np.reshape(simulated, (self.N_rbig, self.N_thetabig))
            interp = interpolate.RectBivariateSpline(-self.rhoobig, self.thetabig, self.sgramsim,kx=1,ky=1)
            self.sgram = interp(-self.rhoo, self.theta)
            self.lines = np.reshape(self.sgram, (-1, 1))

        else:
            simulated = self.radonoperator @ self.flattened
            maxvalue = np.max(simulated)
            noiserealization = np.random.randn(self.N_r * self.N_theta, 1)
            self.lines = simulated + maxvalue * self.noise * noiserealization
            self.sgram = np.reshape(self.lines, (self.N_r, self.N_theta))

        if lhdev is None:
            if self.noise == 0:
                lhdev = 0.01
            else:
                lhdev = self.noise
        self.lhsigmsq = (maxvalue * lhdev) ** 2
        self.Q = argumentspack(M=self.radonoperator, y=self.lines, b=0.01, s2=self.lhsigmsq)
        self.pbar = None
        self.method =   'L-BFGS-B'

    def mincb(self,_):
        self.pbar.update(1)

    def map_tikhonov(self, alpha=1.0, order=1,maxiter=400,retim=True):
        res = None
        if not retim:
            res = container(alpha=alpha,crimefree=self.crimefree, prior='tikhonov', levels=order, method='map', noise=self.noise, imagefilename=self.filename,
                            target=self.targetimage, targetsize=self.dim,globalprefix=self.globalprefix, theta=self.theta/(2*np.pi)*360)
        if (order == 2):
            regvalues = np.array([2, -1, -1, -1, -1])
            offsets = np.array([0, 1, -1, self.dim - 1, -self.dim + 1])
            reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        else:
            regvalues = np.array([1, -1, 1])
            offsets = np.array([-self.dim + 1, 0, 1])
            reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        alpha = alpha
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        print("Running MAP estimate for Tikhonov prior.")
        self.pbar = tqdm(total=np.Inf,file=sys.stdout)
        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        solution = minimize(self.tfun_tikhonov, x0, method=self.method, jac=self.grad_tikhonov,
                            options={'maxiter': maxiter, 'disp': False},callback=self.mincb)
        self.pbar.close()
        iters = solution.nit
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution,error=self.difference(solution),iters=iters)
            return res
        else:
            return solution

    def tfun_tikhonov(self, x):
        return -ltikhonov(x, self.Q)

    def grad_tikhonov(self, x):
        x = x.reshape((-1, 1))
        ans = -tikhonov_grad(x, self.Q)
        return np.ravel(ans)

    def map_tv(self, alpha=1.0, maxiter=400,retim=True):
        res = None
        if not retim:
            res = container(alpha=alpha,crimefree=self.crimefree, prior='tv', method='map', noise=self.noise, imagefilename=self.filename,
                            target=self.targetimage, targetsize=self.dim,globalprefix=self.globalprefix, theta=self.theta/(2*np.pi)*360)
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.01
        print("Running MAP estimate for TV prior.")
        self.pbar = tqdm(total=np.Inf,file=sys.stdout)
        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        solution = minimize(self.tfun_tv, x0, method=self.method, jac=self.grad_tv,
                            options={'maxiter': maxiter, 'disp': False},callback=self.mincb)
        self.pbar.close()
        iters = solution.nit
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution,error=self.difference(solution),iters=iters)
            return res
        else:
            return solution

    def tfun_tv(self, x):
        return -ltv(x, self.Q)

    def grad_tv(self, x):
        x = x.reshape((-1, 1))
        q = -tv_grad(x, self.Q)
        return np.ravel(q)

    def map_cauchy(self, alpha=0.05, maxiter=400,retim=True):
        res = None
        if not retim:
            res = container(alpha=alpha,crimefree=self.crimefree,prior='cauchy',method='map',noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.01
        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        print("Running MAP estimate for Cauchy prior.")
        self.pbar = tqdm(total=np.Inf,file=sys.stdout)
        solution = minimize(self.tfun_cauchy, x0, method=self.method, jac=self.grad_cauchy,
                            options={'maxiter': maxiter, 'disp': False},callback=self.mincb)
        self.pbar.close()
        iters = solution.nit
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution,error=self.difference(solution),iters=iters)
            return res
        else:
            return solution

    def tfun_cauchy(self, x):
        return -lcauchy(x, self.Q)

    def grad_cauchy(self, x):
        x = x.reshape((-1, 1))
        ans = -cauchy_grad(x, self.Q)
        return (np.ravel(ans))

    def map_wavelet(self, alpha=1.0, type='haar', maxiter=400,levels=None ,retim=True):
        res = None
        if (levels is None):
            levels = int(np.floor(np.log2(self.dim))-1)
        if not retim:
            res = container(alpha=alpha,crimefree=self.crimefree,prior=type,method='map',levels=levels,noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from matrices import totalmatrix
        wl = pywt.Wavelet(type)
        g = np.array(wl.dec_lo)
        h = np.array(wl.dec_hi)
        regx = totalmatrix(self.dim, levels, g, h)
        regy = sp.csc_matrix((1, self.dim * self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        self.Q.Lx = regx
        self.Q.Ly = regy
        self.Q.a = alpha
        self.Q.b = 0.01
        self.Q.s2 = self.lhsigmsq
        print("Running MAP estimate for Besov prior (" + type + ' '  + str(levels) + ').' )
        self.pbar = tqdm(total=np.Inf,file=sys.stdout)
        x0 = 1 + 0.05 * np.random.randn(self.dim * self.dim, )
        solution = minimize(self.tfun_tv, x0, method=self.method, jac=self.grad_tv,
                            options={'maxiter': maxiter, 'disp': False},callback=self.mincb)
        self.pbar.close()
        iters = solution.nit
        solution = solution.x
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution), iters=iters)
            return res
        else:
            return solution

    def hmcmc_tikhonov(self, alpha, M=100, Madapt=20, order=1,mapstart=False,thinning=1,retim=True,variant='hmc'):
        res = None
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,adaptnum=Madapt,alpha=alpha,prior='tikhonov',method=variant,levels=order,noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from cyt import hmc, ehmc
        if (order == 2):
            regvalues = np.array([2, -1, -1, -1, -1])
            offsets = np.array([0, 1, -1, self.dim - 1, -self.dim + 1])
            reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        else:
            regvalues = np.array([1, -1, 1])
            offsets = np.array([-self.dim + 1, 0, 1])
            reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.01
        self.Q.logdensity = ltikhonov
        self.Q.gradi = tikhonov_grad
        self.Q.y = self.lines
        if (mapstart):
            x0 = np.reshape(self.map_tikhonov(alpha,maxiter=150),(-1,1))
            x0 = x0 + 0.01*np.random.rand(self.dim*self.dim,1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running  " + variant.upper() + " for Tikhonov prior.")
        if (variant == 'hmc'):
            solution, chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, epsilonwanted=None, kappa=0.75,cmonly=retim, thinning=thinning)
        else:
            solution, chain = ehmc(M, x0, self.Q, Madapt, kappa=0.75, cmonly=retim,thinning=thinning)
        #solution,chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, kappa=0.75, cmonly=retim,thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def hmcmc_tv(self, alpha, M=100, Madapt=20,mapstart=False,thinning=1,retim=True,variant='hmc'):
        res = None
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,adaptnum=Madapt,alpha=alpha,prior='tv',method=variant,noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from cyt import hmc, ehmc
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.01
        self.Q.logdensity = ltv
        self.Q.gradi = tv_grad
        if mapstart:
            x0 = np.reshape(self.map_tv(alpha, maxiter=150), (-1, 1))
            x0 = x0 + 0.00001 * np.random.rand(self.dim * self.dim, 1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running " + variant.upper() + " for TV prior.")
        if (variant == 'hmc'):
            solution, chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, epsilonwanted=None, kappa=0.75,cmonly=retim, thinning=thinning)
        else:
            solution, chain = ehmc(M, x0, self.Q, Madapt,  cmonly=retim,thinning=thinning)
        #solution,chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, kappa=0.75, cmonly=retim,thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def hmcmc_cauchy(self, alpha, M=100, Madapt=20,thinning=1,mapstart=False,retim=True,variant='hmc'):
        res = None
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,adaptnum=Madapt,alpha=alpha,prior='cauchy',method=variant,noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from cyt import hmc, ehmc
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.01
        self.Q.logdensity = lcauchy
        self.Q.gradi = cauchy_grad
        if mapstart:
            x0 = np.reshape(self.map_cauchy(alpha, maxiter=150), (-1, 1))
            x0 = x0 + 0.00001 * np.random.rand(self.dim * self.dim, 1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running " + variant.upper() + " for Cauchy prior.")
        #solution,chain = nonuts_hmc(M, x0, self.Q, 10, L=100, delta=0.65,cmonly=False, thinning=thinning)
        #solution,chain = ehmc(M, x0, self.Q, epstrials=25,Ltrials=25, L=50, delta=0.65,cmonly=False, thinning=thinning)
        #solution = np.median(chain,axis=1)
        if(variant=='hmc'):
            solution,chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, epsilonwanted=None, kappa=0.75, cmonly=retim, thinning=thinning)
        else:
            solution,chain = ehmc(M, x0, self.Q, Madapt, cmonly=retim, thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def hmcmc_wavelet(self, alpha, M=100, Madapt=20, type='haar',levels=None,mapstart=False,thinning=1,retim=True,variant='hmc'):
        res = None
        if (levels is None):
            levels = int(np.floor(np.log2(self.dim))-1)
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,adaptnum=Madapt,levels=levels,alpha=alpha,prior=type,method=variant,noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from matrices import totalmatrix
        from cyt import hmc, ehmc
        wl = pywt.Wavelet(type)
        g = np.array(wl.dec_lo)
        h = np.array(wl.dec_hi)
        regx = totalmatrix(self.dim, levels, g, h)
        regy = sp.csc_matrix((1, self.dim * self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        self.Q.Lx = regx
        self.Q.b = 0.01
        self.Q.Ly = regy
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.logdensity = ltv
        self.Q.gradi = tv_grad
        if mapstart:
            x0 = np.reshape(self.map_wavelet(alpha, type=type, levels=levels, maxiter=150), (-1, 1))
            x0 = x0 + 0.000001 * np.random.rand(self.dim * self.dim, 1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running " + variant.upper() + " for Besov prior (" + type + ' '  + str(levels) + ').' )
        if (variant == 'hmc'):
            solution, chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, epsilonwanted=None, kappa=0.75,cmonly=retim, thinning=thinning)
        else:
            solution, chain = ehmc(M, x0, self.Q, Madapt,  cmonly=retim,thinning=thinning)
        #solution,chain = hmc(M, x0, self.Q, Madapt, de=0.65, gamma=0.05, t0=10.0, epsilonwanted=None, kappa=0.75, cmonly=retim,thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def mwg_tv(self, alpha, M=10000, Madapt=1000,mapstart=False,thinning=10,retim=True):
        res = None
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,adaptnum=Madapt,alpha=alpha,prior='tv',method='mwg',noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from cyt import mwg_tv as mwgt
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.00
        self.Q.y = self.lines
        if (mapstart):
            x0 = np.reshape(self.map_tv(alpha, maxiter=150), (-1, 1))
            x0 = x0 + 0.000001 * np.random.rand(self.dim * self.dim, 1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running MwG MCMC for TV prior.")
        solution,chain= mwgt(M, Madapt, self.Q, x0, sampsigma=1.0, cmonly=retim,thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def mwg_cauchy(self, alpha, M=10000, Madapt=1000,mapstart=False,thinning=10,retim=True):
        res = None
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,adaptnum=Madapt,alpha=alpha,prior='cauchy',method='mwg',noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from cyt import mwg_cauchy as mwgc
        regvalues = np.array([1, -1, 1])
        offsets = np.array([-self.dim + 1, 0, 1])
        reg1d = sp.diags(regvalues, offsets, shape=(self.dim, self.dim))
        regx = sp.kron(sp.eye(self.dim), reg1d)
        regy = sp.kron(reg1d, sp.eye(self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        combined = sp.vstack([regy, regx], format='csc')
        empty = sp.csc_matrix((1, self.dim * self.dim))
        self.Q.Lx = combined
        self.Q.Ly = empty
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        self.Q.b = 0.01
        self.Q.y = self.lines
        if mapstart:
            x0 = np.reshape(self.map_cauchy(alpha, maxiter=150), (-1, 1))
            x0 = x0 + 0.000001 * np.random.rand(self.dim * self.dim, 1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running MwG MCMC for Cauchy prior.")
        solution, chain = mwgc(M, Madapt, self.Q, x0, sampsigma=1.0, cmonly=retim, thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def mwg_wavelet(self, alpha, M=10000, Madapt=1000,type='haar',levels=None,mapstart=False,thinning=10,retim=True):
        res = None
        if (levels is None):
            levels = int(np.floor(np.log2(self.dim))-1)
        if not retim:
            res = container(crimefree=self.crimefree,totaliternum=M,levels=levels,adaptnum=Madapt,alpha=alpha,prior=type,method='mwg',noise=self.noise,imagefilename=self.filename,target=self.targetimage,targetsize=self.dim,globalprefix=self.globalprefix,theta=self.theta/(2*np.pi)*360)
        from matrices import totalmatrix
        from cyt import mwg_tv as mwgt
        wl = pywt.Wavelet(type)
        g = np.array(wl.dec_lo)
        h = np.array(wl.dec_hi)
        regx = totalmatrix(self.dim, levels, g, h)
        regy = sp.csc_matrix((1, self.dim * self.dim))
        regx = sp.csc_matrix(regx)
        regy = sp.csc_matrix(regy)
        self.radonoperator = sp.csc_matrix(self.radonoperator)
        alpha = alpha
        self.Q.Lx = regx
        self.Q.b = 0.0000
        self.Q.Ly = regy
        self.Q.a = alpha
        self.Q.s2 = self.lhsigmsq
        if (mapstart):
            x0 = np.reshape(self.map_wavelet(alpha, type=type,levels=levels, maxiter=150), (-1, 1))
            x0 = x0 + 0.000001 * np.random.rand(self.dim * self.dim, 1)
        else:
            x0 = 0.2 + 0.01*np.random.randn(self.dim * self.dim, 1)
        print("Running MwG MCMC for Besov prior (" + type + ' '  + str(levels) + ').' )
        solution,chain= mwgt(M, Madapt, self.Q, x0, sampsigma=1.0, cmonly=retim,thinning=thinning)
        solution = np.reshape(solution, (-1, 1))
        solution = np.reshape(solution, (self.dim, self.dim))
        if not retim:
            res.finish(result=solution, error=self.difference(solution),chain=chain,thinning=thinning)
            return res
        else:
            return solution

    def target(self):
        return self.targetimage

    def sinogram(self):
        plt.imshow(self.sgram, extent=[self.theta[0], self.theta[-1], -np.sqrt(2), np.sqrt(2)])
        plt.show()

    def radonww(self,image, theta_in_angles,circle=False):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return radon(image, theta_in_angles, circle)

    def difference(self,img):
        t = np.ravel(np.reshape(self.targetimage,(1,-1)))
        r = np.ravel(np.reshape(img,(1,-1)))
        L1 = np.linalg.norm(t-r,ord=1)/np.linalg.norm(t,ord=1)
        L2 = np.linalg.norm(t-r,ord=2)/np.linalg.norm(t,ord=2)
        return L1,L2

    def correlationrow(self,M):
        if (len(M.shape) <= 1 or M.shape[0] <= 1):
            M = M - np.mean(M)
            M = correlate(M, M, mode='full', method='fft')
            M = M[int((M.shape[0] - 1) / 2):]
            return M / M[0]

        else:
            M = M - np.mean(M, axis=1, keepdims=True)
            M = np.apply_along_axis(lambda x: correlate(x, x, mode='full', method='fft'), axis=1, arr=M)
            M = M[:, int((M.shape[1] - 1) / 2):]
            return M / np.reshape(M[:, 0], (-1, 1))

    def saveresult(self,result):
        import h5py
        filename = self.globalprefix + result.prefix + ".hdf5"
        path = os.path.dirname(os.path.abspath(filename))
        if not os.path.exists(path):
            os.makedirs(path)
        with h5py.File(filename, 'w') as f:
            for key, value in result.__dict__.items():
                if (value is None):
                    value = "None"
                if (isinstance(value, np.ndarray)):
                    compression = 'gzip'
                    value = value.astype(np.float32)
                else:
                    compression = None
                f.create_dataset(key, data=value, compression=compression)
        f.close()


if __name__ == "__main__":
    import os
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

    parser = argparse.ArgumentParser()
    parser.add_argument('--file-name', default="shepp.png", type=str, help='Image filename. Default=shepp.png')
    parser.add_argument('--targetsize', default=64, type=int, help='Input image is scaled to this size. Default=64')
    parser.add_argument('--crimefree', default=False, type=bool, help='Simulate sinogram with larger grid and interpolate. Default=False')
    parser.add_argument('--meas-noise', default=0.01, type=float, help='Measurement noise. Default=0.01')
    parser.add_argument('--itheta', default=50,nargs="+", type=int, help='Range and/or number of radon measurement '
    'angles in degrees. One must enter either 3 values (start angle, end angle, number of angles) or just the number of angles, in case the range 0-180 is assumed. Default=50')
    parser.add_argument('--globalprefix', default="/results/", type=str, help='Relative prefix to the script itself, if one wants to save the results. Default= /results/')
    parser.add_argument('--sampler', default="map", type=str, help='Method to use: hmc, mwg or map. Default= map')
    parser.add_argument('--levels', default=None, type=int, help='Number of DWT levels to be used. Default=None means automatic.')
    parser.add_argument('--prior', default="cauchy", type=str,
                        help='Prior to use: tikhonov, cauchy, tv or wavelet. Default= cauchy')
    parser.add_argument('--wave', default="haar", type=str, help='DWT type to use with wavelets. Default=haar')
    parser.add_argument('--samples-num', default=200, type=int,
                        help='Number of samples to be generated within MCMC methods. Default=200, which should be completed within minutes by HMC at small dimensions.')
    parser.add_argument('--thinning', default=1, type=int,
                        help='Thinning factor for MCMC methods.  Default=1 is suitable for HMC, MwG might need thinning between 10-500. ')
    parser.add_argument('--adapt-num', default=50, type=int, help='Number of adaptations in MCMC. Default=50, which roughly suits for HMC.')
    parser.add_argument('--alpha', default=1.0, type=float,
                        help='Prior alpha (regulator constant). Default=1.0, which is rather bad for all priors.')
    parser.add_argument('--omit', default=False, type=bool,
                        help='Omit the command line arguments parsing section in the main.py')
    args = parser.parse_args()

    if len(sys.argv) > 1 and (args.omit is False):
        t = tomography(filename=args.file_name, targetsize=args.targetsize, itheta=args.itheta, noise=args.meas_noise,crimefree=args.crimefree,commonprefix=args.globalprefix)
        real = t.target()
        r = None
        if args.sampler == "hmc":
            if args.prior == "cauchy":
                r = t.hmcmc_cauchy(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,thinning=args.thinning)
            elif args.prior == "tv":
                r = t.hmcmc_tv(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,thinning=args.thinning)
            elif args.prior == "wavelet":
                r = t.hmcmc_wavelet(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,type=args.wave,levels=args.levels,thinning=args.thinning)
            elif args.prior == "tikhonov":
                r = t.hmcmc_tikhonov(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,thinning=args.thinning)
        elif args.sampler == "mwg":
            if args.prior == "cauchy":
                r = t.mwg_cauchy(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,thinning=args.thinning)
            elif args.prior == "tv":
                r = t.mwg_tv(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,thinning=args.thinning)
            elif args.prior == "wavelet":
                r = t.mwg_wavelet(alpha=args.alpha, M=args.samples_num, Madapt=args.adapt_num,type=args.wave,levels=args.levels,thinning=args.thinning)
        elif args.sampler == "map":
            if args.prior == "cauchy":
                r = t.map_cauchy(alpha=args.alpha)
            elif args.prior == "tv":
                r = t.map_tv(alpha=args.alpha)
            elif args.prior == "wavelet":
                r = t.map_wavelet(alpha=args.alpha,type=args.wave,levels=args.levels)
            elif args.prior == "tikhonov":
                r = t.map_tikhonov(alpha=args.alpha)

        plt.imshow(r)
        plt.show()

    # If we do not care the command line.
    else:

        #https://stackoverflow.com/questions/19189274/nested-defaultdict-of-defaultdict
        from collections import defaultdict
        import json
        class NestedDefaultDict(defaultdict):
            def __init__(self, *args, **kwargs):
                super(NestedDefaultDict, self).__init__(NestedDefaultDict, *args, **kwargs)

            def __repr__(self):
                return repr(dict(self))


        '''
        angles = {'sparsestwhole': 15, 'sparsewhole': 45, 'whole': 90, 'sparsestlimited': (0, 45, 15),
                  'sparselimited': (0, 45, 45), 'limited': (0, 45, 90)}
        noises = ( 0.02,)
        sizes = (1024,)

        
        alphas = np.geomspace(0.1,1000,15)
        tikhoalpha = NestedDefaultDict()
        for size in sizes:
            for angletype,angle in angles.items():
                    for noise in noises:
                        bestl2 = np.Inf
                        best = 0
                        t = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                        t2 = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                        for alpha in alphas:
                            res = t.map_tikhonov(alpha, retim=False,maxiter=500)
                            res2 = t2.map_tikhonov(alpha, retim=False, maxiter=500)
                            if ((res.l2 + res2.l2)/2.0 < bestl2):
                                best = alpha
                                bestl2 = (res.l2 + res2.l2)/2.0
                        tikhoalpha[angletype][size][noise] = best

        jsontik = json.dumps(tikhoalpha)
        f = open("tikhonov_002.json", "w")
        f.write(jsontik)
        f.close()
        print(tikhoalpha)

        alphas = np.geomspace(0.1, 1000, 15)
        tvalpha = NestedDefaultDict()
        for size in sizes:
            for angletype, angle in angles.items():
                for noise in noises:
                    bestl2 = np.Inf
                    best = 0
                    t = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                    t2 = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                    for alpha in alphas:
                        res = t.map_tv(alpha, retim=False, maxiter=500)
                        res2 = t2.map_tv(alpha, retim=False, maxiter=500)
                        if ((res.l2 + res2.l2) / 2.0 < bestl2):
                            best = alpha
                            bestl2 = (res.l2 + res2.l2) / 2.0
                    tvalpha[angletype][size][noise] = best

        jsontv = json.dumps(tvalpha)
        f = open("tv_002.json", "w")
        f.write(jsontv)
        f.close()
        print(tvalpha)

        alphas = np.geomspace(0.000001, 2, 15)
        cauchyalpha = NestedDefaultDict()
        for size in sizes:
            for angletype, angle in angles.items():
                for noise in noises:
                    bestl2 = np.Inf
                    best = 0
                    t = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                    t2 = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                    for alpha in alphas:
                        res = t.map_cauchy(alpha, retim=False, maxiter=500)
                        res2 = t2.map_cauchy(alpha, retim=False, maxiter=500)
                        if ((res.l2 + res2.l2) / 2.0 < bestl2):
                            best = alpha
                            bestl2 = (res.l2 + res2.l2) / 2.0
                    cauchyalpha[angletype][size][noise] = best

        jsoncau= json.dumps(cauchyalpha)
        f = open("cauchy_002.json", "w")
        f.write(jsoncau)
        f.close()
        print(cauchyalpha)

        alphas = np.geomspace(0.01, 1000, 15)
        haaralpha = NestedDefaultDict()
        for size in sizes:
            for angletype, angle in angles.items():
                for noise in noises:
                    bestl2 = np.Inf
                    best = 0
                    t = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                    t2 = tomography("shepp.png", size, angle, noise, crimefree=True, commonprefix='/results/')
                    for alpha in alphas:
                        res = t.map_wavelet(alpha, type='haar', retim=False, maxiter=500)
                        res2 = t2.map_wavelet(alpha, type='haar', retim=False, maxiter=500)
                        if ((res.l2 + res2.l2) / 2.0 < bestl2):
                            best = alpha
                            bestl2 = (res.l2 + res2.l2) / 2.0
                    haaralpha[angletype][size][noise] = best

        jsonhaar = json.dumps(haaralpha)
        f = open("haar_002.json", "w")
        f.write(jsonhaar)
        f.close()
        print(haaralpha)
        exit(0)
       
        #4 image sizes, 6 angle types, 3 noise levels
        #tikhoalpha =  {"sparsestwhole": {64: {0.01: 30.0, 0.05: 6.821428571428571, 0.1: 4.714285714285714}, 128: {0.01: 25.785714285714285, 0.05: 4.714285714285714, 0.1: 2.607142857142857}, 256: {0.01: 2.607142857142857, 0.05: 6.821428571428571, 0.1: 4.714285714285714}, 512: {0.01: 2.607142857142857, 0.05: 8.928571428571429, 0.1: 4.714285714285714}}, "sparsewhole": {64: {0.01: 30.0, 0.05: 8.928571428571429, 0.1: 4.714285714285714}, 128: {0.01: 30.0, 0.05: 4.714285714285714, 0.1: 4.714285714285714}, 256: {0.01: 23.67857142857143, 0.05: 6.821428571428571, 0.1: 4.714285714285714}, 512: {0.01: 15.25, 0.05: 6.821428571428571, 0.1: 4.714285714285714}}, "whole": {64: {0.01: 30.0, 0.05: 17.357142857142858, 0.1: 6.821428571428571}, 128: {0.01: 30.0, 0.05: 6.821428571428571, 0.1: 4.714285714285714}, 256: {0.01: 30.0, 0.05: 6.821428571428571, 0.1: 4.714285714285714}, 512: {0.01: 19.464285714285715, 0.05: 8.928571428571429, 0.1: 6.821428571428571}}, "sparsestlimited": {64: {0.01: 30.0, 0.05: 17.357142857142858, 0.1: 6.821428571428571}, 128: {0.01: 19.464285714285715, 0.05: 6.821428571428571, 0.1: 6.821428571428571}, 256: {0.01: 11.035714285714286, 0.05: 4.714285714285714, 0.1: 4.714285714285714}, 512: {0.01: 15.25, 0.05: 4.714285714285714, 0.1: 6.821428571428571}}, "sparselimited": {64: {0.01: 30.0, 0.05: 30.0, 0.1: 13.142857142857142}, 128: {0.01: 30.0, 0.05: 6.821428571428571, 0.1: 6.821428571428571}, 256: {0.01: 27.892857142857142, 0.05: 8.928571428571429, 0.1: 6.821428571428571}, 512: {0.01: 23.67857142857143, 0.05: 8.928571428571429, 0.1: 6.821428571428571}}, "limited": {64: {0.01: 30.0, 0.05: 30.0, 0.1: 21.571428571428573}, 128: {0.01: 30.0, 0.05: 11.035714285714286, 0.1: 8.928571428571429}, 256: {0.01: 30.0, 0.05: 11.035714285714286, 0.1: 8.928571428571429}, 512: {0.01: 30.0, 0.05: 11.035714285714286, 0.1: 6.821428571428571}}}
        tikhoalpha = {"sparsestwhole": {64: {0.02: 26.207413942088984, 0.05: 7.218038036465943, 0.1: 3.760603093086394}, 128: {0.02: 14.247868454254814, 0.05: 5.2100073095869135, 0.1: 3.760603093086394}, 256: {0.02: 10.505404060985274, 0.05: 5.2100073095869135, 0.1: 3.760603093086394}, 512: {0.02: 10.505404060985274, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}}, "sparsewhole": {64: {0.02: 35.54359110848588, 0.05: 10.0, 0.1: 5.2100073095869135}, 128: {0.02: 14.247868454254814, 0.05: 5.2100073095869135, 0.1: 3.760603093086394}, 256: {0.02: 10.505404060985274, 0.05: 5.2100073095869135, 0.1: 3.760603093086394}, 512: {0.02: 14.247868454254814, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}}, "whole": {64: {0.02: 88.66918395150992, 0.05: 19.193831036664843, 0.1: 7.218038036465943}, 128: {0.02: 19.323555220846075, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}, 256: {0.02: 14.247868454254814, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}, 512: {0.02: 14.247868454254814, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}}, "sparsestlimited": {64: {0.02: 65.37859386891436, 0.05: 19.193831036664843, 0.1: 7.218038036465943}, 128: {0.02: 7.745966692414836, 0.05: 5.2100073095869135, 0.1: 5.2100073095869135}, 256: {0.02: 5.711346241581194, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}, 512: {0.02: 5.711346241581194, 0.05: 7.218038036465943, 0.1: 5.2100073095869135}}, "sparselimited": {64: {0.02: 221.19948878068303, 0.05: 36.84031498640386, 0.1: 13.854180248814739}, 128: {0.02: 19.323555220846075, 0.05: 10.0, 0.1: 5.2100073095869135}, 256: {0.02: 10.505404060985274, 0.05: 10.0, 0.1: 5.2100073095869135}, 512: {0.02: 10.505404060985274, 0.05: 7.218038036465943, 0.1: 7.218038036465943}}, "limited": {64: {0.02: 360.9019018232971, 0.05: 70.71067811865474, 0.1: 19.193831036664843}, 128: {0.02: 35.54359110848588, 0.05: 13.854180248814739, 0.1: 7.218038036465943}, 256: {0.02: 19.323555220846075, 0.05: 13.854180248814739, 0.1: 7.218038036465943}, 512: {0.02: 14.247868454254814, 0.05: 10.0, 0.1: 7.218038036465943}}}
        #tvalpha = {"sparsestwhole": {64: {0.01: 25.0, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 128: {0.01: 1.8785714285714286, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 256: {0.01: 1.8785714285714286, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 512: {0.01: 1.8785714285714286, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}}, "sparsewhole": {64: {0.01: 25.0, 0.05: 5.435714285714285, 0.1: 1.8785714285714286}, 128: {0.01: 25.0, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 256: {0.01: 7.2142857142857135, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 512: {0.01: 1.8785714285714286, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}}, "whole": {64: {0.01: 25.0, 0.05: 10.77142857142857, 0.1: 3.657142857142857}, 128: {0.01: 25.0, 0.05: 3.657142857142857, 0.1: 1.8785714285714286}, 256: {0.01: 23.22142857142857, 0.05: 3.657142857142857, 0.1: 1.8785714285714286}, 512: {0.01: 5.435714285714285, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}}, "sparsestlimited": {64: {0.01: 25.0, 0.05: 8.992857142857142, 0.1: 3.657142857142857}, 128: {0.01: 3.657142857142857, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 256: {0.01: 1.8785714285714286, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 512: {0.01: 1.8785714285714286, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}}, "sparselimited": {64: {0.01: 25.0, 0.05: 25.0, 0.1: 7.2142857142857135}, 128: {0.01: 14.328571428571427, 0.05: 1.8785714285714286, 0.1: 3.657142857142857}, 256: {0.01: 5.435714285714285, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 512: {0.01: 3.657142857142857, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}}, "limited": {64: {0.01: 25.0, 0.05: 25.0, 0.1: 14.328571428571427}, 128: {0.01: 25.0, 0.05: 3.657142857142857, 0.1: 1.8785714285714286}, 256: {0.01: 8.992857142857142, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}, 512: {0.01: 8.992857142857142, 0.05: 1.8785714285714286, 0.1: 1.8785714285714286}}}
        tvalpha = {"sparsestwhole": {64: {0.02: 7.745966692414828, 0.05: 1.817120592832139, 0.1: 1.2646221415587084}, 128: {0.02: 1.2646221415587084, 0.05: 0.880111736793393, 0.1: 0.6125123416602171}, 256: {0.02: 0.6125123416602171, 0.05: 0.880111736793393, 0.1: 0.6125123416602171}, 512: {0.02: 0.880111736793393, 0.05: 1.2646221415587084, 0.1: 0.880111736793393}}, "sparsewhole": {64: {0.02: 33.01927248894624, 0.05: 5.390793008259619, 0.1: 2.6109990805829466}, 128: {0.02: 7.745966692414828, 0.05: 2.6109990805829466, 0.1: 1.2646221415587084}, 256: {0.02: 3.7517136868608247, 0.05: 1.817120592832139, 0.1: 0.880111736793393}, 512: {0.02: 1.817120592832139, 0.05: 1.2646221415587084, 0.1: 0.880111736793393}}, "whole": {64: {0.02: 68.17316198804991, 0.05: 11.13008789394615, 0.1: 3.7517136868608247}, 128: {0.02: 15.99269160920534, 0.05: 3.7517136868608247, 0.1: 1.817120592832139}, 256: {0.02: 7.745966692414828, 0.05: 2.6109990805829466, 0.1: 1.2646221415587084}, 512: {0.02: 3.7517136868608247, 0.05: 1.817120592832139, 0.1: 1.2646221415587084}}, "sparsestlimited": {64: {0.02: 47.44500197193054, 0.05: 11.13008789394615, 0.1: 2.6109990805829466}, 128: {0.02: 2.6109990805829466, 0.05: 1.817120592832139, 0.1: 1.817120592832139}, 256: {0.02: 0.2966667721187179, 0.05: 1.817120592832139, 0.1: 1.2646221415587084}, 512: {0.02: 0.880111736793393, 0.05: 1.2646221415587084, 0.1: 1.817120592832139}}, "sparselimited": {64: {0.02: 140.75355588178843, 0.05: 33.01927248894624, 0.1: 7.745966692414828}, 128: {0.02: 3.7517136868608247, 0.05: 1.817120592832139, 0.1: 1.817120592832139}, 256: {0.02: 2.6109990805829466, 0.05: 2.6109990805829466, 0.1: 1.817120592832139}, 512: {0.02: 1.2646221415587084, 0.05: 1.817120592832139, 0.1: 1.817120592832139}}, "limited": {64: {0.02: 290.606492579008, 0.05: 47.44500197193054, 0.1: 15.99269160920534}, 128: {0.02: 7.745966692414828, 0.05: 3.7517136868608247, 0.1: 1.817120592832139}, 256: {0.02: 3.7517136868608247, 0.05: 2.6109990805829466, 0.1: 2.6109990805829466}, 512: {0.02: 2.6109990805829466, 0.05: 1.817120592832139, 0.1: 1.817120592832139}}}
        #cauchyalpha = {"sparsestwhole": {64: {0.01: 0.057058823529411766, 0.05: 0.039705882352941174, 0.1: 0.23058823529411765}, 128: {0.01: 0.005, 0.05: 0.10911764705882354, 0.1: 0.26529411764705885}, 256: {0.01: 0.005, 0.05: 0.1264705882352941, 0.1: 0.24794117647058825}, 512: {0.01: 0.005, 0.05: 0.1264705882352941, 0.1: 0.17852941176470588}}, "sparsewhole": {64: {0.01: 0.005, 0.05: 0.02235294117647059, 0.1: 0.1264705882352941}, 128: {0.01: 0.07441176470588236, 0.05: 0.039705882352941174, 0.1: 0.24794117647058825}, 256: {0.01: 0.039705882352941174, 0.05: 0.10911764705882354, 0.1: 0.24794117647058825}, 512: {0.01: 0.02235294117647059, 0.05: 0.10911764705882354, 0.1: 0.21323529411764708}}, "whole": {64: {0.01: 0.005, 0.05: 0.005, 0.1: 0.02235294117647059}, 128: {0.01: 0.005, 0.05: 0.039705882352941174, 0.1: 0.1438235294117647}, 256: {0.01: 0.09176470588235294, 0.05: 0.02235294117647059, 0.1: 0.17852941176470588}, 512: {0.01: 0.02235294117647059, 0.05: 0.09176470588235294, 0.1: 0.1611764705882353}}, "sparsestlimited": {64: {0.01: 0.3, 0.05: 0.005, 0.1: 0.10911764705882354}, 128: {0.01: 0.005, 0.05: 0.26529411764705885, 0.1: 0.23058823529411765}, 256: {0.01: 0.23058823529411765, 0.05: 0.23058823529411765, 0.1: 0.21323529411764708}, 512: {0.01: 0.10911764705882354, 0.05: 0.19588235294117648, 0.1: 0.19588235294117648}}, "sparselimited": {64: {0.01: 0.005, 0.05: 0.005, 0.1: 0.005}, 128: {0.01: 0.005, 0.05: 0.23058823529411765, 0.1: 0.21323529411764708}, 256: {0.01: 0.10911764705882354, 0.05: 0.23058823529411765, 0.1: 0.21323529411764708}, 512: {0.01: 0.09176470588235294, 0.05: 0.17852941176470588, 0.1: 0.1264705882352941}}, "limited": {64: {0.01: 0.005, 0.05: 0.005, 0.1: 0.005}, 128: {0.01: 0.005, 0.05: 0.005, 0.1: 0.26529411764705885}, 256: {0.01: 0.02235294117647059, 0.05: 0.19588235294117648, 0.1: 0.23058823529411765}, 512: {0.01: 0.005, 0.05: 0.1611764705882353, 0.1: 0.1611764705882353}}}
        cauchyalpha = {"sparsestwhole": {64: {0.02: 0.0011892071150027212, 0.05: 0.05318295896944989, 0.1: 0.17817974362806763}, 128: {0.02: 0.009360637232664544, 0.05: 0.09734539534337833, 0.1: 0.32613788179066194}, 256: {0.02: 0.004100966752495598, 0.05: 0.09734539534337833, 0.1: 0.32613788179066194}, 512: {0.02: 0.0017966648943927722, 0.05: 0.09734539534337833, 0.1: 0.17817974362806763}}, "sparsewhole": {64: {0.02: 0.00015108090691070758, 0.05: 0.008672488792828026, 0.1: 0.09734539534337833}, 128: {0.02: 0.07368062997280773, 0.05: 0.05318295896944989, 0.1: 0.17817974362806763}, 256: {0.02: 0.032280047427433914, 0.05: 0.09734539534337833, 0.1: 0.32613788179066194}, 512: {0.02: 0.01414213562373095, 0.05: 0.09734539534337833, 0.1: 0.17817974362806763}}, "whole": {64: {0.02: 0.0001, 0.05: 0.004738062997279315, 0.1: 0.05318295896944989}, 128: {0.02: 0.01414213562373095, 0.05: 0.05318295896944989, 0.1: 0.09734539534337833}, 256: {0.02: 0.07368062997280773, 0.05: 0.029055582082430587, 0.1: 0.17817974362806763}, 512: {0.02: 0.021366066756874972, 0.05: 0.09734539534337833, 0.1: 0.17817974362806763}}, "sparsestlimited": {64: {0.02: 0.0005210007309586913, 0.05: 0.004738062997279315, 0.1: 0.09734539534337833}, 128: {0.02: 0.002714417616594907, 0.05: 0.32613788179066194, 0.1: 0.17817974362806763}, 256: {0.02: 0.5799642800220423, 0.05: 0.17817974362806763, 0.1: 0.17817974362806763}, 512: {0.02: 0.16817928305074292, 0.05: 0.17817974362806763, 0.1: 0.17817974362806763}}, "sparselimited": {64: {0.02: 3.3503164750652652e-06, 0.05: 0.00042211342507443144, 0.1: 0.004738062997279315}, 128: {0.02: 2.054539912180901e-05, 0.05: 0.17817974362806763, 0.1: 0.17817974362806763}, 256: {0.02: 6.883358916458818e-05, 0.05: 0.32613788179066194, 0.1: 0.17817974362806763}, 512: {0.02: 0.17817974362806763, 0.05: 0.17817974362806763, 0.1: 0.17817974362806763}}, "limited": {64: {0.02: 2.765365240491261e-06, 0.05: 6.132375635173039e-06, 0.1: 0.00042211342507443144}, 128: {0.02: 0.0002689296879997083, 0.05: 3.7606030930863934e-05, 0.1: 0.17817974362806763}, 256: {0.02: 9.72492472466073e-05, 0.05: 0.17817974362806763, 0.1: 0.17817974362806763}, 512: {0.02: 0.12026901270703146, 0.05: 0.17817974362806763, 0.1: 0.17817974362806763}}}
        #haaralpha = {"sparsestwhole": {64: {0.01: 30.0, 0.05: 4.371428571428571, 0.1: 2.2357142857142858}, 128: {0.01: 8.642857142857142, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}, 256: {0.01: 2.2357142857142858, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}, 512: {0.01: 4.371428571428571, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}}, "sparsewhole": {64: {0.01: 30.0, 0.05: 12.914285714285713, 0.1: 4.371428571428571}, 128: {0.01: 30.0, 0.05: 4.371428571428571, 0.1: 2.2357142857142858}, 256: {0.01: 6.507142857142856, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}, 512: {0.01: 2.2357142857142858, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}}, "whole": {64: {0.01: 30.0, 0.05: 25.728571428571428, 0.1: 8.642857142857142}, 128: {0.01: 30.0, 0.05: 8.642857142857142, 0.1: 4.371428571428571}, 256: {0.01: 15.049999999999999, 0.05: 4.371428571428571, 0.1: 2.2357142857142858}, 512: {0.01: 4.371428571428571, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}}, "sparsestlimited": {64: {0.01: 30.0, 0.05: 12.914285714285713, 0.1: 4.371428571428571}, 128: {0.01: 2.2357142857142858, 0.05: 4.371428571428571, 0.1: 2.2357142857142858}, 256: {0.01: 0.1, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}, 512: {0.01: 0.1, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}}, "sparselimited": {64: {0.01: 30.0, 0.05: 30.0, 0.1: 12.914285714285713}, 128: {0.01: 23.592857142857145, 0.05: 8.642857142857142, 0.1: 4.371428571428571}, 256: {0.01: 2.2357142857142858, 0.05: 4.371428571428571, 0.1: 2.2357142857142858}, 512: {0.01: 2.2357142857142858, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}}, "limited": {64: {0.01: 30.0, 0.05: 30.0, 0.1: 19.321428571428573}, 128: {0.01: 30.0, 0.05: 8.642857142857142, 0.1: 4.371428571428571}, 256: {0.01: 4.371428571428571, 0.05: 6.507142857142856, 0.1: 4.371428571428571}, 512: {0.01: 2.2357142857142858, 0.05: 2.2357142857142858, 0.1: 2.2357142857142858}}}
        haaralpha = {"sparsestwhole": {64: {0.02: 18.138420703071393, 0.05: 4.832930238571752, 0.1: 2.9763514416313175}, 128: {0.02: 5.462408915159338, 0.05: 2.9763514416313175, 0.1: 1.8329807108324356}, 256: {0.02: 3.661388283197873, 0.05: 1.8329807108324356, 0.1: 1.1288378916846888}, 512: {0.02: 3.661388283197873, 0.05: 1.8329807108324356, 0.1: 1.1288378916846888}}, "sparsewhole": {64: {0.02: 60.230259343740826, 0.05: 12.742749857031335, 0.1: 4.832930238571752}, 128: {0.02: 12.157969509318965, 0.05: 4.832930238571752, 0.1: 2.9763514416313175}, 256: {0.02: 5.462408915159338, 0.05: 2.9763514416313175, 0.1: 1.8329807108324356}, 512: {0.02: 2.4541853911988967, 0.05: 1.8329807108324356, 0.1: 1.1288378916846888}}, "whole": {64: {0.02: 134.05764160338668, 0.05: 20.6913808111479, 0.1: 7.847599703514611}, 128: {0.02: 27.0606292727936, 0.05: 7.847599703514611, 0.1: 4.832930238571752}, 256: {0.02: 8.149343595525918, 0.05: 4.832930238571752, 0.1: 2.9763514416313175}, 512: {0.02: 5.462408915159338, 0.05: 2.9763514416313175, 0.1: 1.8329807108324356}}, "sparsestlimited": {64: {0.02: 60.230259343740826, 0.05: 12.742749857031335, 0.1: 4.832930238571752}, 128: {0.02: 12.157969509318965, 0.05: 4.832930238571752, 0.1: 2.9763514416313175}, 256: {0.02: 0.33205900518969655, 0.05: 2.9763514416313175, 0.1: 1.8329807108324356}, 512: {0.02: 0.22257523554448713, 0.05: 1.8329807108324356, 0.1: 1.1288378916846888}}, "sparselimited": {64: {0.02: 241.64651192858759, 0.05: 33.59818286283781, 0.1: 12.742749857031335}, 128: {0.02: 12.157969509318965, 0.05: 7.847599703514611, 0.1: 4.832930238571752}, 256: {0.02: 3.661388283197873, 0.05: 4.832930238571752, 0.1: 2.9763514416313175}, 512: {0.02: 0.7390811129476478, 0.05: 1.8329807108324356, 0.1: 1.8329807108324356}}, "limited": {64: {0.02: 572.5142703256575, 0.05: 88.58667904100822, 0.1: 20.6913808111479}, 128: {0.02: 18.138420703071393, 0.05: 7.847599703514611, 0.1: 4.832930238571752}, 256: {0.02: 8.149343595525918, 0.05: 4.832930238571752, 0.1: 2.9763514416313175}, 512: {0.02: 1.6450115280080442, 0.05: 2.9763514416313175, 0.1: 1.8329807108324356}}}

        angles = {'sparsestwhole': 15, 'sparsewhole': 45, 'whole': 90, 'sparsestlimited': (0, 45, 15),
                  'sparselimited': (0, 45, 45), 'limited': (0, 45, 90)}
        noises = (0.02, 0.05, 0.1)
        sizes = (64, 128, 256, 512) #
        '''

        # Big image and one noise level
        #tikhoalpha = {"sparsestwhole": {1024: {0.05: 19.306977288832496}}, "sparsewhole": {1024: {0.05: 10.0}}, "whole": {1024: {0.05: 19.306977288832496}}, "sparsestlimited": {1024: {0.05: 5.17947467923121}}, "sparselimited": {1024: {0.05: 19.306977288832496}}, "limited": {1024: {0.05: 19.306977288832496}}}
        #tvalpha = {"sparsestwhole": {1024: {0.05: 2.6826957952797246}}, "sparsewhole": {1024: {0.05: 2.6826957952797246}}, "whole": {1024: {0.05: 2.6826957952797246}}, "sparsestlimited": {1024: {0.05: 5.17947467923121}}, "sparselimited": {1024: {0.05: 2.6826957952797246}}, "limited": {1024: {0.05: 2.6826957952797246}}}
        #cauchyalpha = {"sparsestwhole": {1024: {0.05: 0.08929132803668435}}, "sparsewhole": {1024: {0.05: 0.08929132803668435}}, "whole": {1024: {0.05: 0.08929132803668435}}, "sparsestlimited": {1024: {0.05: 0.08929132803668435}}, "sparselimited": {1024: {0.05: 0.08929132803668435}}, "limited": {1024: {0.05: 0.08929132803668435}}}
        #haaralpha = {"sparsestwhole": {1024: {0.05: 1.3894954943731375}}, "sparsewhole": {1024: {0.05: 1.3894954943731375}}, "whole": {1024: {0.05: 3.1622776601683795}}, "sparsestlimited": {1024: {0.05: 1.3894954943731375}}, "sparselimited": {1024: {0.05: 3.1622776601683795}}, "limited": {1024: {0.05: 3.1622776601683795}}}

        tikhoalpha = {'sparsestwhole': {1024: {0.05: 19.306977288832496, 0.02: 10.0}}, 'sparsewhole': {1024: {0.05: 10.0, 0.02: 19.306977288832496}}, 'whole': {1024: {0.05: 19.306977288832496, 0.02: 19.306977288832496}}, 'sparsestlimited': {1024: {0.05: 5.17947467923121, 0.02: 10.0}}, 'sparselimited': {1024: {0.05: 19.306977288832496, 0.02: 10.0}}, 'limited': {1024: {0.05: 19.306977288832496, 0.02: 19.306977288832496}}}
        tvalpha = {'sparsestwhole': {1024: {0.05: 2.6826957952797246, 0.02: 2.6826957952797246}}, 'sparsewhole': {1024: {0.05: 2.6826957952797246, 0.02: 2.6826957952797246}}, 'whole': {1024: {0.05: 2.6826957952797246, 0.02: 5.17947467923121}}, 'sparsestlimited': {1024: {0.05: 5.17947467923121, 0.02: 1.3894954943731375}}, 'sparselimited': {1024: {0.05: 2.6826957952797246, 0.02: 2.6826957952797246}}, 'limited': {1024: {0.05: 2.6826957952797246, 0.02: 2.6826957952797246}}}
        cauchyalpha = {'sparsestwhole': {1024: {0.05: 0.08929132803668435, 0.02: 0.0005016969106227038}}, 'sparsewhole': {1024: {0.05: 0.08929132803668435, 0.02: 0.003986470631277378}}, 'whole': {1024: {0.05: 0.08929132803668435, 0.02: 0.003986470631277378}}, 'sparsestlimited': {1024: {0.05: 0.08929132803668435, 0.02: 0.08929132803668435}}, 'sparselimited': {1024: {0.05: 0.08929132803668435, 0.02: 0.08929132803668435}}, 'limited': {1024: {0.05: 0.08929132803668435, 0.02: 0.08929132803668435}}}
        haaralpha = {'sparsestwhole': {1024: {0.05: 1.3894954943731375, 0.02: 3.1622776601683795}}, 'sparsewhole': {1024: {0.05: 1.3894954943731375, 0.02: 3.1622776601683795}}, 'whole': {1024: {0.05: 3.1622776601683795, 0.02: 3.1622776601683795}}, 'sparsestlimited': {1024: {0.05: 1.3894954943731375, 0.02: 0.2682695795279726}}, 'sparselimited': {1024: {0.05: 3.1622776601683795, 0.02: 0.6105402296585329}}, 'limited': {1024: {0.05: 3.1622776601683795, 0.02: 3.1622776601683795}}}

        angles = {'sparsewhole': 45, 'sparselimited': (0, 45, 45) }
        noises = (0.02,)
        sizes = (1024,)
        #angles = {'sparsestwhole': 15, 'sparsewhole': 45, 'whole': 90, 'sparsestlimited': (0, 45, 15),'sparselimited': (0, 45, 45), 'limited': (0, 45, 90)}

        for _ in range(0,1):
            for size in sizes:
                for angletype,theta in angles.items():
                    for noise in noises:
                        t = tomography("shepp.png", size, theta, noise, crimefree=True, commonprefix='/results/')

                        res = t.map_tikhonov(tikhoalpha[angletype][size][noise], order=1, retim=False)
                        t.saveresult(res)

                        res = t.map_tv(tvalpha[angletype][size][noise], retim=False)
                        t.saveresult(res)

                        res = t.map_cauchy(cauchyalpha[angletype][size][noise], retim=False)
                        t.saveresult(res)

                        res = t.map_wavelet(haaralpha[angletype][size][noise], type='haar', retim=False)
                        t.saveresult(res)

                        res = t.mwg_tv(tvalpha[angletype][size][noise], mapstart=True, M=100000, Madapt=50000,
                                       retim=False, thinning=250)
                        t.saveresult(res)

                        res = t.mwg_cauchy(cauchyalpha[angletype][size][noise], mapstart=True, M=100000, Madapt=50000,
                                           retim=False, thinning=250)
                        t.saveresult(res)

                        res = t.mwg_wavelet(haaralpha[angletype][size][noise], mapstart=True, type='haar', M=100000,
                                            Madapt=50000, retim=False, thinning=250)
                        t.saveresult(res)

                        res = t.hmcmc_tv(tvalpha[angletype][size][noise], mapstart=True, M=350, Madapt=50, retim=False,
                                         thinning=1)
                        t.saveresult(res)

                        res = t.hmcmc_cauchy(cauchyalpha[angletype][size][noise], mapstart=True, M=350, Madapt=50,
                                             retim=False, thinning=1)
                        t.saveresult(res)

                        res = t.hmcmc_wavelet(haaralpha[angletype][size][noise], mapstart=True, M=350, Madapt=50,
                                              retim=False, thinning=1)
                        t.saveresult(res)

                        res = t.hmcmc_tv(tvalpha[angletype][size][noise], mapstart=True, M=350, Madapt=50, retim=False,
                                         thinning=1, variant='ehmc')
                        t.saveresult(res)

                        res = t.hmcmc_cauchy(cauchyalpha[angletype][size][noise], mapstart=True, M=350, Madapt=50,
                                             retim=False, thinning=1, variant='ehmc')
                        t.saveresult(res)

                        res = t.hmcmc_wavelet(haaralpha[angletype][size][noise], mapstart=True, M=350, Madapt=50,
                                              retim=False, thinning=1, variant='ehmc')
                        t.saveresult(res)


        #t = tomography("shepp.png", 128, theta, 0.05, crimefree=True, commonprefix='/results/')
        #t.sinogram()
        #reg = np.array([1,2.5,5,10])
        #reg = np.array([5,7,12])

        #reg = np.array([7,12,17])
        # reg = np.array([5])
        # for rv in reg:
        #     res = t.map_wavelet(rv,type='haar',levels=None,retim=False)
        #     print(res.l1,res.l2)
        #     t.saveresult(res)
        #     plt.imshow(res.result)
        #     plt.clim(0, 1)
        #     plt.show()

        #exit(0)
        #reg = np.array([0.02])
        # reg = np.array([12])
        # for rv in reg:
        #     res = t.map_tikhonov(rv, retim=False)
        #     print(res.l1, res.l2)
        #     t.saveresult(res)
        #     plt.imshow(res.result)
        #     plt.clim(0, 1)
        #     plt.show()


        # res = t.map_cauchy(0.02, retim=False)
        # print(res.l1, res.l2)
        # t.saveresult(res)
        # plt.imshow(res.result)
        # plt.clim(0, 1)
        # plt.show()
        #
        # res = t.mwg_cauchy(0.02,retim=False,mapstart=True,M=5000,Madapt=1000,thinning=200)
        # #res = t.hmcmc_cauchy(3, retim=False, mapstart=True, M=200, Madapt=40, thinning=10)
        # print(res.l1, res.l2)
        # t.saveresult(res)
        # plt.imshow(res.result)
        # plt.clim(0, 1)
        # plt.show()


        # np.random.seed(3)
        # #theta = (0, 90, 50)
        # theta = 50
        # t = tomography("shepp.png", 64, theta, 0.05, crimefree=True,commonprefix='/results/')
        # real = t.target()
        # # t.saveresult(real)
        # sg = t.sinogram()
        # #t.sinogram()
        #
        # # t.normalizedsgram = t.radonww()
        # #t.sinogram()
        #
        # # sg2 = t.radonww()
        # # t = tomography("shepp.png",0.1,20,0.2)
        # # r = t.mwg_cauchy(0.01,5000,200)
        # # r = t.hmcmc_tv(5,250,30)
        # # r = t.hmcmc_cauchy(0.1,150,30)
        # # r = t.hmcmc_tikhonov(50, 200, 20)
        # # #r = t.hmcmc_wavelet(25, 250, 20,type='haar')
        # # #print(np.linalg.norm(real - r))
        # # # tt = time.time()
        # # #
        # #r = t.map_wavelet(5)
        # res = t.mwg_cauchy(0.01, 200, 100, thinning=10, mapstart=False, retim=False)
        # #res = t.hmcmc_cauchy(0.01, 230, 30, thinning=1, mapstart=True, retim=False)
        # t.saveresult(res)
        # #
        # r = res.result
        # # plt.plot(res.chain[5656,:])
        # # plt.figure()
        # print(t.difference(r))
        # # r = t.map_cauchy(0.01,True)
        #
        # # r = t.map_tikhonov(10,True,order=1)
        # # #
        # # # # # print(time.time()-tt)
        # # # # #
        # # r = t.hmcmc_cauchy(0.01,100,20)
        # # r = t.mwg_cauchy(0.01, 1000, 100)
        # # print(time.time()-tt)
        # # r = t.hmcmc_tv(10, 200, 20)
        # # r = t.hmcmc_cauchy(100/(t.dim**2), 250, 30)
        # plt.imshow(r)
        # # # # #plt.plot(r[3000,:],r[2000,:],'*r')
        # plt.clim(0, 1)
        # plt.figure()
        # #r2 = t.hmcmc_cauchy(0.001, 200, 20)
        # r2 = t.map_cauchy(0.01)
        # #r2 = t.map_cauchy(0.001)
        # #r2 = t.mwg_wavelet(10,5000,2000,levels=6,mapstart=True)
        # #r2 = t.mwg_tv( 5,2000,200)
        # #r2 = t.map_tv(5)
        # # # #print(np.linalg.norm(real - r))
        # # # #q = iradon_sart(q, theta=theta)
        # # # #r2 = t.map_tikhonov(50.0)
        # # # #tt = time.time()
        # # r2 = t.map_tikhonov(1)
        # # r2 = t.map_wavelet(0.5,'db2')
        # print(t.difference(r2))
        # # # # #print(time.time()-tt)
        # plt.imshow(r2)
        # plt.clim(0, 1)
        # plt.show()

#
#
